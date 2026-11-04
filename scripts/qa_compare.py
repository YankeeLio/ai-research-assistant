"""对比问答：同一问题在抽取式与大模型模式下的输出差异。

用法:
    python scripts/qa_compare.py [doc_id]
"""

from __future__ import annotations

import sys

import httpx

QUESTIONS = [
    "这篇论文最大的模型有多少参数？",
    "训练时用了多少块 GPU、什么型号？",
]


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=600) as client:
        docs = client.get("/api/documents").json()
        doc_id = sys.argv[1] if len(sys.argv) > 1 else docs[0]["doc_id"]
        target = next((d for d in docs if d["doc_id"] == doc_id), docs[0])
        print(f"文档: {target['title'][:60]} ({doc_id})")
        client.post(f"/api/documents/{doc_id}/index")

        for q in QUESTIONS:
            print(f"\n== {q}")
            resp = client.post("/api/qa/ask", json={"doc_id": doc_id, "question": q, "top_k": 8})
            data = resp.json()
            print("mode:", data["mode"], "| warnings:", data["warnings"])
            print("answer:", data["answer"][:500])
            print("evidence:", [(e["chunk_id"], e["page"] + 1) for e in data["evidence"][:4]])


if __name__ == "__main__":
    main()
