"""清理文献库里的重复条目，只保留演示需要的那一份。

- 1706.03762v7.pdf：保留一份（矢量版，用于问答/对比/图谱）
- 1706.03762v1.pdf：删除（去重演示时现场上传即可）
- 1706.03762v1_img.pdf：保留（扫描件演示）
"""

from __future__ import annotations

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=180) as client:
        docs = client.get("/api/documents").json()
        seen_v7 = False
        for doc in docs:
            name = doc["file_name"]
            doc_id = doc["doc_id"]
            if name.endswith("1706.03762v7.pdf"):
                if seen_v7:
                    client.delete(f"/api/documents/{doc_id}")
                    print(f"删除重复 v7: {doc_id}")
                else:
                    seen_v7 = True
            elif name.endswith("1706.03762v1.pdf"):
                client.delete(f"/api/documents/{doc_id}")
                print(f"删除 v1（现场演示再上传）: {doc_id}")

        remaining = client.get("/api/documents").json()
        print(f"\n剩余 {len(remaining)} 篇：")
        for doc in remaining:
            print(f"  {doc['page_count']:>3}p  {doc['title'][:52]}")


if __name__ == "__main__":
    main()
