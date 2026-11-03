"""端到端冒烟测试：健康检查 → 上传 → 列表 → 拉取解析结果。

用法:
    python scripts/smoke_test.py pdf/1706.03762v7.pdf [http://127.0.0.1:8000]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx


def main() -> None:
    pdf = Path(sys.argv[1] if len(sys.argv) > 1 else "pdf/1706.03762v7.pdf")
    base = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"

    with httpx.Client(base_url=base, timeout=180) as client:
        health = client.get("/api/health").json()
        print("health :", json.dumps(health, ensure_ascii=False))

        with pdf.open("rb") as fh:
            resp = client.post(
                "/api/documents/upload",
                files={"file": (pdf.name, fh, "application/pdf")},
            )
        resp.raise_for_status()
        doc = resp.json()
        print("upload :", json.dumps(doc, ensure_ascii=False)[:400])

        docs = client.get("/api/documents").json()
        print(f"list   : {len(docs)} 篇")

        parsed = client.get(f"/api/documents/{doc['doc_id']}/parsed").json()
        stats = parsed.get("stats") or {}
        print("parsed :", fdump(stats))
        print("title  :", parsed.get("title"))
        print("sections:", [s["title"] for s in parsed.get("sections", [])][:8])
        print("refs   :", len(parsed.get("references", [])), "条")
        print("tables :", len(parsed.get("tables", [])), "个")
        print("anchors:", len(parsed.get("cite_anchors", [])), "个")


def fdump(d: dict) -> str:
    keys = ("page_count", "block_count", "heading_count", "reference_count", "cite_anchor_count")
    return " ".join(f"{k}={d.get(k)}" for k in keys)


if __name__ == "__main__":
    main()
