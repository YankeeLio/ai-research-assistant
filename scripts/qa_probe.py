"""检索与问答探针：验证分块、混合检索、引用校验链路。

用法:
    python scripts/qa_probe.py <doc_id> "问题"
"""

from __future__ import annotations

import json
import sys

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    if len(sys.argv) < 3:
        print("用法: python scripts/qa_probe.py <doc_id> <问题>")
        raise SystemExit(1)
    doc_id, question = sys.argv[1], sys.argv[2]

    with httpx.Client(base_url=BASE, timeout=300) as client:
        idx = client.post(f"/api/documents/{doc_id}/index").json()
        print("索引:", json.dumps(idx, ensure_ascii=False))

        hits = client.get(f"/api/documents/{doc_id}/search", params={"q": question, "top_k": 4}).json()
        print(f"\n--- 检索命中 {len(hits['hits'])} 条 ---")
        for h in hits["hits"]:
            print(f"  [{h['score']:.3f}] p{h['page'] + 1} {h['section'][:30]:30s} {h['text'][:70]}")

        ans = client.post("/api/qa/ask", json={"doc_id": doc_id, "question": question}).json()
        print(f"\n--- 回答 (mode={ans['mode']}) ---")
        print(ans["answer"][:600])
        print(f"\n证据 {len(ans['evidence'])} 条, warnings={ans['warnings']}")


if __name__ == "__main__":
    main()
