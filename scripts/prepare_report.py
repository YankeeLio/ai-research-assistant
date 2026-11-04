"""把技术文档里的图片路径改成本地 assets/，并复制截图。

用法:
    python scripts/prepare_report.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "report" / "report.html"
SHOTS = ROOT / "assets" / "shots"
TARGET = ROOT / "docs" / "report" / "assets"


def main() -> None:
    html = REPORT.read_text(encoding="utf-8")
    html = html.replace("../assets/shots/", "assets/")
    REPORT.write_text(html, encoding="utf-8")

    TARGET.mkdir(parents=True, exist_ok=True)
    count = 0
    for png in SHOTS.glob("*.png"):
        shutil.copy2(png, TARGET / png.name)
        count += 1
    print(f"图片路径已重写，复制 {count} 张截图到 {TARGET}")


if __name__ == "__main__":
    main()
