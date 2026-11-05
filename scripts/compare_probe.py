"""跨文献对比探针：验证多篇检索 + 维度化对比 + 引用校验。"""

from __future__ import annotations

import httpx

QUESTION = "BERT 与 Transformer Encoder 在结构上有什么承袭与差异？"


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=600) as client:
        docs = client.get("/api/documents").json()
        by_title = {d["title"][:40]: d["doc_id"] for d in docs}
        bert = next((v for k, v in by_title.items() if k.startswith("BERT")), None)
        attn = next((v for k, v in by_title.items() if k.startswith("Attention")), None)
        if not bert or not attn:
            print("缺少 BERT 或 Attention，先运行 seed_demo.py")
            print("现有文档:", list(by_title.keys()))
            return
        print(f"对比: {bert[:8]} vs {attn[:8]}")

        r = client.post("/api/qa/compare", json={"doc_ids": [attn, bert], "question": QUESTION})
        print("status", r.status_code)
        data = r.json()
        print("mode:", data.get("mode"), "| warnings:", data.get("warnings"))
        print("docs:", [d["title"][:30] for d in data.get("docs", [])])
        print("\nanswer:\n", data.get("answer", "")[:900])
        ev = data.get("evidence", [])
        print(f"\nevidence {len(ev)} 条，按文档分布：")
        for item in ev[:8]:
            print(f"  [{item['chunk_id']}] {item['title'][:22]:24s} p{item['page'] + 1}")


if __name__ == "__main__":
    main()
