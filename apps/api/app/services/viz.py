"""CSV → 学术图表 + 自动 Figure Caption。

图表类型不是让用户选，而是按数据形状判断：
- 一列类别 + 一列数值 → 柱状图
- 一列序号/时间 + 一列数值 → 折线图
- 两列数值 → 散点图
- 多列数值 → 分组柱状图

Caption 也不是套模板空话：峰值、拐点、趋势斜率都从数据里算出来，
写进图注的数字与图上画出来的必须是同一份数据。
"""

from __future__ import annotations

import csv
import io
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 服务端渲染，不依赖 GUI 后端
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from ..core.config import get_settings  # noqa: E402

# 学术图表配色：色盲友好的低饱和序列，避免默认亮蓝橙
PALETTE = ["#1F4E63", "#A63C2A", "#6B8E4E", "#8B6E4E", "#5A5A66", "#B08968"]

matplotlib.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman"],
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "grid.linewidth": 0.6,
        "figure.dpi": 200,
        "savefig.dpi": 200,
    }
)


@dataclass
class Column:
    name: str
    kind: str  # numeric | category
    values: list = field(default_factory=list)


@dataclass
class CsvTable:
    columns: list[Column]
    rows: int

    def numeric(self) -> list[Column]:
        return [c for c in self.columns if c.kind == "numeric"]

    def category(self) -> list[Column]:
        return [c for c in self.columns if c.kind == "category"]


def parse_csv(text: str) -> CsvTable:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(io.StringIO(text), dialect)
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if len(rows) < 2:
        raise ValueError("CSV 至少需要表头 + 一行数据")

    header = [h.strip() or f"col{i}" for i, h in enumerate(rows[0])]
    body = rows[1:]
    columns: list[Column] = []
    for idx, name in enumerate(header):
        raw = [r[idx].strip() if idx < len(r) else "" for r in body]
        numeric: list[float] = []
        ok = 0
        for cell in raw:
            value = _to_float(cell)
            numeric.append(value if value is not None else math.nan)
            if value is not None:
                ok += 1
        if raw and ok >= max(2, len(raw) * 0.8):
            columns.append(Column(name=name, kind="numeric", values=numeric))
        else:
            columns.append(Column(name=name, kind="category", values=raw))
    return CsvTable(columns=columns, rows=len(body))


def _to_float(cell: str) -> float | None:
    if not cell:
        return None
    cleaned = cell.replace(",", "").replace("%", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def choose_chart(table: CsvTable) -> str:
    nums, cats = table.numeric(), table.category()
    if len(nums) >= 2 and not cats:
        return "scatter" if len(nums) == 2 else "grouped_bar"
    if len(nums) >= 2:
        return "grouped_bar"
    if len(nums) == 1 and cats:
        return "line" if _looks_sequential(cats[0].values) else "bar"
    return "bar"


def _looks_sequential(values: list[str]) -> bool:
    """判断首列是否像时间/序号：全是数字串，或能解析成年份/日期。"""
    if not values:
        return False
    parsed = 0
    for v in values[:20]:
        token = v.strip()
        if not token:
            continue
        if token.replace(".", "", 1).isdigit() or token[:4].isdigit():
            parsed += 1
    return parsed >= len(values[:20]) * 0.8


def render_chart(csv_text: str, title: str = "", chart_type: str | None = None) -> dict:
    table = parse_csv(csv_text)
    kind = chart_type or choose_chart(table)
    nums, cats = table.numeric(), table.category()

    if not nums:
        raise ValueError("CSV 中找不到数值列，无法绘图")

    figure_id = uuid.uuid4().hex[:12]
    path = get_settings().data_dir / "figures" / f"{figure_id}.png"
    path.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    labels = cats[0].values if cats else [str(i + 1) for i in range(table.rows)]
    summary: list[str] = []

    if kind == "line":
        x = _x_axis(labels)
        y = nums[0].values
        ax.plot(x, y, color=PALETTE[0], linewidth=1.6, marker="o", markersize=3)
        ax.set_xlabel(cats[0].name if cats else "index")
        ax.set_ylabel(nums[0].name)
        summary.append(_describe_series(nums[0].name, y))
    elif kind == "scatter":
        ax.scatter(nums[0].values, nums[1].values, s=22, color=PALETTE[1], alpha=0.85)
        ax.set_xlabel(nums[0].name)
        ax.set_ylabel(nums[1].name)
        r = _pearson(nums[0].values, nums[1].values)
        if r is not None:
            summary.append(f"{nums[0].name} 与 {nums[1].name} 的皮尔逊相关系数为 {r:.2f}")
    elif kind == "grouped_bar":
        shown = nums[:4]
        groups = _split_by_magnitude(shown)
        if len(groups) > 1:
            # 量级差 20 倍以上还画在同一根轴上，小数值会被压成一条线——这是误导而非美观问题
            plt.close(fig)
            fig, axes = plt.subplots(
                len(groups), 1, figsize=(6.4, 2.4 * len(groups)), sharex=True
            )
            axes = np.atleast_1d(axes)
            x = np.arange(len(labels))
            for ax_i, group in zip(axes, groups):
                width = 0.8 / len(group)
                for i, col in enumerate(group):
                    ax_i.bar(
                        x + i * width,
                        col.values,
                        width=width,
                        label=col.name,
                        color=PALETTE[(i + len(group)) % len(PALETTE)],
                    )
                ax_i.legend(frameon=False, fontsize=7.5, loc="upper left")
                ax_i.set_ylabel("value", fontsize=8)
            axes[-1].set_xticks(x + 0.4 - 0.4 / len(groups[-1]))
            axes[-1].set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
            ax = axes[0]
            summary.append(
                "因各指标量级相差超过 20 倍，图中拆为 "
                + " / ".join("、".join(c.name for c in g) for g in groups)
                + " 两组子图，避免小量级序列被压缩"
            )
        else:
            width = 0.8 / len(shown)
            x = np.arange(len(labels))
            for i, col in enumerate(shown):
                ax.bar(
                    x + i * width, col.values, width=width, label=col.name, color=PALETTE[i % len(PALETTE)]
                )
            ax.set_xticks(x + width * (len(shown) - 1) / 2)
            rotate = len(labels) > 5 or any(len(str(l)) > 10 for l in labels)
            ax.set_xticklabels(labels, rotation=25 if rotate else 0, ha="right" if rotate else "center")
            ax.legend(frameon=False, fontsize=8)
        for col in shown:
            summary.append(_describe_series(col.name, col.values))
    else:
        y = nums[0].values
        ax.bar(labels, y, color=PALETTE[0], width=0.62)
        ax.set_xlabel(cats[0].name if cats else "index")
        ax.set_ylabel(nums[0].name)
        ax.tick_params(axis="x", rotation=30 if len(labels) > 6 else 0)
        summary.append(_describe_series(nums[0].name, y))

    if title:
        ax.set_title(title, fontsize=10.5, pad=8)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    caption = build_caption(title, kind, table, summary)
    return {
        "figure_id": figure_id,
        "url": f"/api/figures/{figure_id}.png",
        "chart_type": kind,
        "caption": caption,
        "summary": summary,
        "rows": table.rows,
        "columns": [{"name": c.name, "kind": c.kind} for c in table.columns],
    }


def _split_by_magnitude(columns: list[Column], ratio: float = 20.0) -> list[list[Column]]:
    """按数量级分组：最大值相差 20 倍以上的序列不应画在同一根纵轴上。"""
    if len(columns) <= 1:
        return [columns]
    scales = []
    for col in columns:
        values = [v for v in col.values if not math.isnan(v)]
        scales.append(max(values) if values else 0.0)
    maxima = sorted(s for s in scales if s > 0)
    if len(maxima) < 2 or maxima[-1] <= maxima[0] * ratio:
        return [columns]

    big = [c for c, s in zip(columns, scales) if s >= maxima[-1] / 10]
    small = [c for c, s in zip(columns, scales) if s < maxima[-1] / 10]
    groups = [g for g in (small, big) if g]
    return groups if len(groups) > 1 else [columns]


def _x_axis(labels: list[str]) -> list:
    """折线图横轴：能转数字就用数字，否则退回序号并把标签写进刻度。"""
    numbers = [_to_float(v) for v in labels]
    if all(n is not None for n in numbers):
        return numbers
    return list(range(len(labels)))


def _describe_series(name: str, values: list[float]) -> str:
    arr = np.array([v for v in values if not math.isnan(v)], dtype=float)
    if arr.size == 0:
        return f"{name} 无有效数值"
    peak_idx = int(np.argmax(arr))
    trough_idx = int(np.argmin(arr))
    slope = _slope(arr)
    trend = "上升" if slope > 0.02 * abs(arr.mean() or 1) else "下降" if slope < -0.02 * abs(arr.mean() or 1) else "基本持平"
    return (
        f"{name} 取值 {arr.min():.4g}–{arr.max():.4g}，"
        f"在第 {peak_idx + 1} 个数据点达到峰值 {arr[peak_idx]:.4g}，"
        f"最低点出现在第 {trough_idx + 1} 个数据点（{arr[trough_idx]:.4g}），整体呈{trend}趋势"
    )


def _slope(arr: np.ndarray) -> float:
    if arr.size < 2:
        return 0.0
    x = np.arange(arr.size, dtype=float)
    return float(np.polyfit(x, arr, 1)[0])


def _pearson(a: list[float], b: list[float]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if not math.isnan(x) and not math.isnan(y)]
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    if np.std(xs) == 0 or np.std(ys) == 0:
        return None
    return float(np.corrcoef(xs, ys)[0, 1])


def build_caption(title: str, kind: str, table: CsvTable, summary: list[str]) -> str:
    kind_cn = {"bar": "柱状图", "line": "折线图", "scatter": "散点图", "grouped_bar": "分组柱状图"}[kind]
    head = f"{title}。" if title else ""
    body = "；".join(summary)
    return (
        f"{head}图为{kind_cn}，基于 {table.rows} 条样本、"
        f"{len(table.columns)} 个字段（{', '.join(c.name for c in table.columns)}）绘制。{body}。"
        f"数据来源：用户上传的原始 CSV，未做平滑或插值。"
    )


def figure_path(figure_id: str) -> Path:
    from ..core.paths import figure_path as safe_figure_path

    return safe_figure_path(figure_id)
