"""按画面轨的场景时长生成字幕（SRT）与配音用纯文本。

优先读取录制时写下的 `assets/video/frames-demo/timings.json`：
场景边界来自录制墙钟，和成片时间轴同源，字幕不会漂移。
没有 timings.json 时退化为按设计时长比例分配。

成片结构：片头 4 s + 正文 + 片尾 4 s。
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRT_OUT = ROOT / "assets" / "video" / "demo.srt"
TXT_OUT = ROOT / "docs" / "VIDEO_NARRATION.txt"
TIMINGS = ROOT / "assets" / "video" / "frames-demo" / "timings.json"

TITLE_SECONDS = 4.0
END_SECONDS = 4.0

# 场景名 → 旁白行（顺序与录制脚本一致）
NARRATION: dict[str, list[str]] = {
    "镜1 文献台": [
        "科研里最耗时间的不是读论文，而是找论文、核对细节、以及确认自己没记错。",
        "通用聊天机器人能聊，但它会流畅地编造超参数和参考文献——而科研对幻觉是零容忍的。",
        "SciLoom 要解决的就是这件事：把一篇论文从下载到写成综述，织成一条每一步都能回到原文的链路。",
    ],
    "镜2 去重": [
        "先看文献管理。系统基于正文内容做语义去重，不看文件名。",
        "我先入库第七版，再入库第一版——右下角立刻弹出预警：判定为同一工作的不同版本，正文重合度 90.5%，并建议保留库中更新的 v7。",
        "点开修订差异，它按章节对齐，告诉我结论部分改动最大，参考文献从 36 条增加到 40 条。",
    ],
    "镜3 解析结构": [
        "解析不是简单抽文本。标题树由字号、编号和位置共同判定，表格结构化还原，公式单独标记。",
        "更关键的是扫描件：这篇 PDF 没有文本层，系统走 OCR 识别，再把像素坐标按比例反算回 PDF 坐标——所以扫描件和原生 PDF 在上层看来是同一种东西。",
    ],
    "镜4 问答": [
        "这是抗幻觉问答。回答是流式吐出来的，每一句后面都有引用编号，点一下就跳到原文那一页——因为解析阶段就存了字符级坐标。",
        "注意第二个问题的答案：它直接说现有材料不足以回答，只说明型号是 V100，没给数量。",
        "它没有编，这正是我们要的。",
    ],
    "镜5 对比": [
        "勾选 BERT 和原始 Transformer，它会分别检索两篇的证据，统一编号后按维度组织对比：架构来源、实现一致性、基本构件、注意力方向。",
        "每条结论后面都标注了来自哪一篇的哪一页，多文推理同样可追溯。",
    ],
    "镜6 划词": [
        "中文读者可以直接进入对照模式。公式和参考文献不翻译，引用编号原样保留。",
        "两侧同步不是按滚动比例，而是按段落对齐——行高不一样，比例同步会越读越偏。",
        "读到难句，直接划选，译文气泡立刻出来。",
    ],
    "镜7 图谱": [
        "把库里十篇论文放在一起，系统会连出引用网络，用 PageRank 和中介中心性划分角色：Adam、Attention、Layer Normalization 是基石，RoBERTa 是衍生工作。",
        "右侧这段综述不是模型编的，是从图的结构翻译出来的——谁被引几次、时间跨度、有没有环，都能对上。",
    ],
    "镜8 检索": [
        "检索结果不是照搬 arXiv 排序，而是按库内相关性、有没有开源代码、时效重排，并给出理由。",
        "看到合适的，一键下钻：下载、解析、去重、入库、建索引，全自动。",
    ],
    "镜9 写作": [
        "写作环节同样有约束：参考文献只能从库内取，编号越界会被剔除。",
        "数据图表会根据数据形状自动选图——这里 BLEU 和参数量差了两个数量级，它自动拆成上下两个子图，并在图注里写明原因。",
    ],
}


def srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rest = divmod(ms, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def wrap(text: str, width: int = 24) -> str:
    """把一行旁白折成两行，避免字幕横跨整个 1920 画布。"""
    if len(text) <= width:
        return text
    mid = len(text) // 2
    best = None
    for i, ch in enumerate(text):
        if ch in "，。；：、——":
            if best is None or abs(i - mid) < abs(best - mid):
                best = i
    if best is None or not (8 <= best <= len(text) - 6):
        best = mid
    return f"{text[: best + 1]}\n{text[best + 1 :].lstrip('，。；：、')}"


def scene_spans() -> list[tuple[str, float, float]]:
    """返回 [(场景名, 起, 止)]，单位秒，已含片头偏移。"""
    if TIMINGS.exists():
        data = json.loads(TIMINGS.read_text(encoding="utf-8"))
        # offset = 首帧到达时刻 - 第一个场景开始时刻；正片从首帧算起，需要补偿
        offset = float(data.get("offset", 0.0))
        return [
            (s["name"], s["start"] - offset + TITLE_SECONDS, s["end"] - offset + TITLE_SECONDS)
            for s in data["scenes"]
        ]
    # 退化：按设计时长顺序累加
    spans, cursor = [], TITLE_SECONDS
    for name, lines in NARRATION.items():
        span = 40.0
        spans.append((name, cursor, cursor + span))
        cursor += span
    return spans


def main() -> None:
    entries: list[tuple[float, float, str]] = []
    for name, start, end in scene_spans():
        lines = NARRATION.get(name)
        if not lines:
            print("未找到场景旁白:", name)
            continue
        total_chars = sum(len(line) for line in lines) or 1
        cursor = start
        for line in lines:
            share = (end - start) * len(line) / total_chars
            entries.append((cursor, cursor + share, line))
            cursor += share

    blocks = []
    for i, (start, end, text) in enumerate(entries, start=1):
        blocks.append(f"{i}\n{srt_time(start)} --> {srt_time(end)}\n{wrap(text)}\n")

    SRT_OUT.parent.mkdir(parents=True, exist_ok=True)
    SRT_OUT.write_text("\n".join(blocks), encoding="utf-8")

    lines_out = ["SciLoom 智研织机 · 演示视频旁白", "（时间码对应 demo-with-cards.mp4）", ""]
    for start, _end, text in entries:
        lines_out.append(f"[{srt_time(start)[3:8]}] {text}")
    TXT_OUT.write_text("\n".join(lines_out), encoding="utf-8")

    last = entries[-1][1] if entries else 0
    print(f"字幕 {len(entries)} 条 → {SRT_OUT}")
    print(f"旁白稿 → {TXT_OUT}")
    print(f"正文结束于 {last:.1f}s，加片尾共 {last + END_SECONDS:.1f}s")


if __name__ == "__main__":
    main()
