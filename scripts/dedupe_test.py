"""去重与版本差异验证：对应赛题 3.1 测试用例。

流程（与赛题要求一致）：
    1. 先入库最新版 v7
    2. 再入库旧版 v1 → 应检测到"同一工作的不同版本"并建议保留 v7
    3. 重复入库同一文件 → 应判定为完全相同
    4. 对比 v1 → v7 的修订差异
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"


def reset(client: httpx.Client) -> None:
    for doc in client.get("/api/documents").json():
        client.delete(f"/api/documents/{doc['doc_id']}")


def upload(client: httpx.Client, path: Path) -> dict:
    with path.open("rb") as fh:
        resp = client.post("/api/documents/upload", files={"file": (path.name, fh, "application/pdf")})
    resp.raise_for_status()
    return resp.json()


def show(doc: dict) -> None:
    print(f"  入库 {doc['file_name']:24s} id={doc['doc_id']}")
    if doc.get("duplicate_of"):
        print(f"    重复判定: {doc['duplicate_verdict']}  相似度={doc['duplicate_similarity']:.3f}")
        print(f"    建议     : [{doc['duplicate_action']}] {doc['duplicate_message']}")
    else:
        print("    重复判定: 无")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    pdf_dir = root / "pdf"
    with httpx.Client(base_url=BASE, timeout=600) as client:
        print("== 清空文献库 ==")
        reset(client)

        print("\n== 1) 入库最新版 v7 ==")
        v7 = upload(client, pdf_dir / "1706.03762v7.pdf")
        show(v7)

        print("\n== 2) 入库旧版 v1 ==")
        v1 = upload(client, pdf_dir / "1706.03762v1.pdf")
        show(v1)

        print("\n== 3) 重复入库 v7 ==")
        v7_dup = upload(client, pdf_dir / "1706.03762v7.pdf")
        show(v7_dup)

        print("\n== 4) 重复列表 ==")
        dup = client.get(f"/api/documents/{v1['doc_id']}/duplicates").json()
        print(json.dumps(dup, ensure_ascii=False, indent=2)[:600])

        print("\n== 5) v1 → v7 版本差异 ==")
        diff = client.get(f"/api/documents/{v1['doc_id']}/diff/{v7['doc_id']}").json()
        print("摘要:", diff["summary"])
        print("章节变化:")
        for s in diff["sections"]:
            if s["status"] != "unchanged":
                print(
                    f"  {s['status']:9s} {s['title'][:40]:42s} "
                    f"+{s['added_sentences']} / -{s['removed_sentences']}"
                )


if __name__ == "__main__":
    sys.exit(main())
