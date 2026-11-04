"""按当前代码重新解析库内文档（解析器改动后使用）。

用法:
    python scripts/reparse.py            # 全部重解析
    python scripts/reparse.py <doc_id>   # 只重解析一篇
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

from app.core import db  # noqa: E402
from app.services.dedupe import build_fingerprint, save_fingerprint  # noqa: E402
from app.services.parser import PdfParser  # noqa: E402


def main() -> None:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    settings_dir = Path("data") / "docs"
    parser = PdfParser()

    for row in db.list_documents():
        doc_id = row["doc_id"]
        if only and doc_id != only:
            continue
        pdf = settings_dir / doc_id / "original.pdf"
        if not pdf.exists():
            print(f"跳过 {doc_id}（原始文件缺失）")
            continue
        started = time.perf_counter()
        parsed = parser.parse(pdf, doc_id)
        parsed.file_name = row["file_name"]
        db.save_parsed(doc_id, parsed.model_dump())
        save_fingerprint(build_fingerprint(parsed), settings_dir / doc_id)
        stats = parsed.stats
        print(
            f"{doc_id}  {parsed.stats.page_count:3d}p  refs={stats.reference_count:3d}  "
            f"anchors={stats.cite_anchor_count:3d}  {time.perf_counter() - started:5.1f}s  "
            f"{(parsed.title or '')[:44]}"
        )
        db.update_document(doc_id, page_count=stats.page_count)
        # 索引依赖旧文本，删掉让下次检索重建
        idx = settings_dir / doc_id / "index"
        if idx.exists():
            for f in idx.iterdir():
                f.unlink()
            idx.rmdir()
        tr = settings_dir / doc_id / "translation.json"
        if tr.exists():
            tr.unlink()
    print("完成。索引与译文已失效，下次提问/翻译会自动重建。")
    json.dumps({})  # 保持 JSON 可用性检查


if __name__ == "__main__":
    main()
