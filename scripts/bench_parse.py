"""解析性能基准：整篇计时 + 内存峰值，用于长文档优化前后对比。

用法:
    python scripts/bench_parse.py pdf/UnderstandingDeepLearning_02_09_26_C.pdf
"""

from __future__ import annotations

import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

import pymupdf  # noqa: E402

from app.services.parser import PdfParser  # noqa: E402


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "pdf/1706.03762v7.pdf")
    parser = PdfParser()

    doc = pymupdf.open(path)
    page_count = doc.page_count
    doc.close()

    tracemalloc.start()
    t0 = time.perf_counter()
    parsed = parser.parse(path, "bench")
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    stats = parsed.stats
    print(f"文件      : {path.name}   页数={page_count}")
    print(f"解析耗时  : {elapsed:6.1f} s  ({elapsed / max(1, page_count) * 1000:5.0f} ms/页)")
    print(f"内存峰值  : {peak / 1024 / 1024:6.1f} MB")
    if stats:
        print(
            f"产出      : blocks={stats.block_count} headings={stats.heading_count} "
            f"refs={stats.reference_count} tables={stats.table_count} "
            f"anchors={stats.cite_anchor_count} chars={stats.char_count}"
        )


if __name__ == "__main__":
    main()
