"""按文档顺序重排"图 5-N"编号，避免插入新图后出现重号。"""

from __future__ import annotations

import re
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1] / "docs" / "report" / "report.html"


def main() -> None:
    html = REPORT.read_text(encoding="utf-8")
    counter = {"n": 3}

    def repl(match: re.Match[str]) -> str:
        num = counter["n"]
        counter["n"] += 1
        return f'<p class="cap">图 5-{num}　'

    html, count = re.subn(r'<p class="cap">图 5-\d+　', repl, html)
    REPORT.write_text(html, encoding="utf-8")
    print(f"已重排 {count} 个图号（5-3 起）")


if __name__ == "__main__":
    main()
