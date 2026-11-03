"""离线解析探针：不启动服务，直接验证解析质量。

用法:
    python scripts/parse_probe.py pdf/1706.03762v1.pdf
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.services.parser import PdfParser  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/parse_probe.py <pdf路径>")
        raise SystemExit(1)

    path = Path(sys.argv[1])
    parser = PdfParser()
    parsed = parser.parse(path, doc_id="probe")

    print(f"文件        : {parsed.file_name}")
    print(f"标题        : {parsed.title!r}")
    print(f"作者        : {parsed.authors[:5]}")
    print(f"版式        : {parsed.layout}  扫描件: {parsed.is_scanned}")
    print(f"统计        : {parsed.stats.model_dump() if parsed.stats else {}}")
    print("\n--- 标题树 (前 20) ---")
    for s in parsed.sections[:20]:
        print(f"  {'  ' * (s.level - 1)}L{s.level} p{s.page} {s.title[:70]}")
    print("\n--- 参考文献 (前 5) ---")
    for r in parsed.references[:5]:
        print(f"  [{r.index}] p{r.page} {r.text[:90]}")
    print("\n--- 表格 ---")
    for t in parsed.tables[:3]:
        print(f"  {t.id} p{t.page} {len(t.rows)}x{len(t.rows[0]) if t.rows else 0} 首行: {t.rows[0][:4]}")
    print("\n--- 引用锚点 (前 5) ---")
    for a in parsed.cite_anchors[:5]:
        print(f"  [{a.ref_index}] p{a.page} bbox={[round(v) for v in a.bbox]}")

    size_mb = len(json.dumps(parsed.model_dump(), ensure_ascii=False).encode("utf-8")) / 1024 / 1024
    print(f"\n结构化结果体积: {size_mb:.2f} MB（含全部 block 坐标）")


if __name__ == "__main__":
    main()
