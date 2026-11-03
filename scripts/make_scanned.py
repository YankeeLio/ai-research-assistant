"""把矢量 PDF 光栅化为"纯图片"PDF，用于在没有官方扫描件时自测 OCR 链路。

用法:
    python scripts/make_scanned.py pdf/1706.03762v1.pdf pdf/1706.03762v1_img.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf


def main() -> None:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else "pdf/1706.03762v1.pdf")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else "pdf/1706.03762v1_img.pdf")
    dpi = int(sys.argv[3]) if len(sys.argv) > 3 else 150

    src_doc = pymupdf.open(src)
    out = pymupdf.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(new_page.rect, pixmap=pix)
    out.save(dst, deflate=True)
    print(f"已生成 {dst}  ({out.page_count} 页, {dst.stat().st_size / 1024 / 1024:.1f} MB)")
    out.close()
    src_doc.close()


if __name__ == "__main__":
    main()
