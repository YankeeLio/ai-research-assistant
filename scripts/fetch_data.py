"""一键准备官方测试数据集（供复现与评审使用）。

用法:
    python scripts/fetch_data.py

下载内容:
    pdf/1706.03762v1.pdf                          标准矢量 PDF（单栏正文 + 双栏参考文献）
    pdf/1706.03762v7.pdf                          同一论文第七版，用于语义去重
    pdf/UnderstandingDeepLearning_02_09_26_C.pdf  541 页教材，用于长文档压力测试
    pdf/1706.03762v1_img.pdf                      由上者光栅化得到的纯图片 PDF，用于 OCR 自测
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx

PDF_DIR = Path(__file__).resolve().parents[1] / "pdf"
ASSETS = [
    ("1706.03762v1.pdf", "https://arxiv.org/pdf/1706.03762v1"),
    ("1706.03762v7.pdf", "https://arxiv.org/pdf/1706.03762v7"),
    (
        "UnderstandingDeepLearning_02_09_26_C.pdf",
        "https://github.com/udlbook/udlbook/releases/download/v5.0.3/UnderstandingDeepLearning_02_09_26_C.pdf",
    ),
]
UA = {"User-Agent": "Mozilla/5.0 (SciLoom data fetcher)"}


def download(name: str, url: str) -> None:
    target = PDF_DIR / name
    if target.exists() and target.stat().st_size > 100_000:
        print(f"跳过 {name}（已存在 {target.stat().st_size / 1024 / 1024:.1f} MB）")
        return
    print(f"下载 {name} ...")
    with httpx.stream("GET", url, headers=UA, follow_redirects=True, timeout=600) as r:
        r.raise_for_status()
        with target.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 16):
                fh.write(chunk)
    print(f"  -> {target.stat().st_size / 1024 / 1024:.1f} MB")


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    for name, url in ASSETS:
        try:
            download(name, url)
        except Exception as exc:  # noqa: BLE001
            print(f"  下载失败: {exc}", file=sys.stderr)

    scanned = PDF_DIR / "1706.03762v1_img.pdf"
    if not scanned.exists():
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("make_scanned.py")),
             str(PDF_DIR / "1706.03762v1.pdf"), str(scanned), "150"],
            check=False,
        )


if __name__ == "__main__":
    main()
