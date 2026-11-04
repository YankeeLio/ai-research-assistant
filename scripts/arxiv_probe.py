"""arXiv 检索与推荐探针。"""

from __future__ import annotations

import json

import httpx


def main() -> None:
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        print("== 检索（按库内相关性重排）==")
        r = client.get("/api/arxiv/search", params={"q": "all:vision transformer", "max_results": 6})
        print("status", r.status_code)
        data = r.json()
        print(f"命中 {data['count']} 条，库内已过滤 {data.get('filtered_in_library', 0)} 条")
        for item in data["items"][:4]:
            print(f"  score={item['score']:.3f} rel={item['relevance']:.3f} code={'Y' if item['code_url'] else 'N'}")
            print(f"    {item['title'][:70]}")
            print(f"    理由: {'; '.join(item['reasons'])}")

        print("\n== 库内个性化推荐（按提交时间抓最新）==")
        r = client.get("/api/recommend", params={"q": "all:large language model", "top_k": 5})
        print("status", r.status_code)
        rec = r.json()
        for item in rec["items"]:
            print(f"  score={item['score']:.3f} rel={item['relevance']:.3f} {item['published'][:10]} {item['title'][:60]}")
            print(f"    理由: {'; '.join(item['reasons'])}")


if __name__ == "__main__":
    main()
