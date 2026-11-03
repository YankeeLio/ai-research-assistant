import time
from pathlib import Path

import pymupdf

from app.services.ocr import ocr_page_lines

doc = pymupdf.open(Path("pdf/1706.03762v1_img.pdf"))
for dpi in (150, 200):
    t0 = time.perf_counter()
    lines = ocr_page_lines(doc[2], dpi=dpi)
    print(f"dpi={dpi}  页3: {time.perf_counter() - t0:.2f}s  行数={len(lines)}")
    print("  样例:", [t for _, t, _ in lines[:3]])
