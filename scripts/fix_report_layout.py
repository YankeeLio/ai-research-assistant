"""技术文档排版微调：减少整页空白。

问题：若干章节用强制分页，但上一页的表格经常溢出单独一行，
导致"上一页只有一行表、下一页大半空白"。这里只保留主要章节的分页。
"""

from __future__ import annotations

import re
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "docs" / "report" / "report.html"
FLOW_SECTIONS = ("2　需求分析", "3　系统架构设计", "9　局限与展望")


def main() -> None:
    html = REPORT.read_text(encoding="utf-8")

    for section in FLOW_SECTIONS:
        html = html.replace(f'<h2 class="newpage">{section}</h2>', f"<h2>{section}</h2>")

    html = re.sub(r"figure img\{ width:\d+%;", "figure img{ width:88%;", html)
    html = html.replace(
        "figure{ margin:8pt 0 4pt; text-align:center; }",
        "figure{ margin:8pt 0 4pt; text-align:center; page-break-inside:avoid; }",
    )
    REPORT.write_text(html, encoding="utf-8")
    print("排版参数已更新：去掉 3 处分页、图片宽度 88%、图片禁止跨页")


if __name__ == "__main__":
    main()
