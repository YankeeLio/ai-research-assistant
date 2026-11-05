"""把官方测试集与谱系论文灌入目标实例，供部署后的演示使用。

用法:
    python scripts/seed_demo.py                       # 灌入本机 127.0.0.1:8000
    python scripts/seed_demo.py http://1.2.3.4        # 灌入线上实例

空库的演示等于零分：评审打开只看得到一句"导入一篇 PDF 开始"。
这个脚本保证新部署的实例一上线就有 9 篇论文、可用的图谱和推荐。
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = ROOT / "pdf"


def collect_pdfs() -> list[Path]:
    files: list[Path] = []
    for pattern in ("*.pdf", "related/*.pdf"):
        files.extend(sorted(PDF_DIR.glob(pattern)))
    return [f for f in files if f.stat().st_size > 50_000]


def main() -> None:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")
    print(f"目标: {base}")

    with httpx.Client(base_url=base, timeout=900) as client:
        health = client.get("/api/health").json()
        print("健康检查:", health.get("status"), "模型:", health.get("model"))

        existing = {d["file_name"] for d in client.get("/api/documents").json()}
        print(f"库内已有 {len(existing)} 篇")

        for path in collect_pdfs():
            name = path.name
            if name in existing:
                print(f"跳过 {name}")
                continue
            print(f"上传 {name} ({path.stat().st_size / 1024 / 1024:.1f} MB) …")
            with path.open("rb") as fh:
                resp = client.post("/api/documents/upload", files={"file": (name, fh, "application/pdf")})
            if resp.status_code != 200:
                print(f"  失败 {resp.status_code}: {resp.text[:200]}")
                continue
            doc = resp.json()
            tag = f" [{doc['duplicate_verdict']}]" if doc.get("duplicate_of") else ""
            print(f"  ok {doc['page_count']} 页{tag}")

        docs = client.get("/api/documents").json()
        print(f"\n入库完成，共 {len(docs)} 篇。开始建索引（每篇 5-20 秒）…")
        skipped = 0
        for doc in docs:
            # 541 页教材在 CPU 上建索引要跑几十分钟，会把其余文档全堵住；
            # 它只用于演示"长文档解析"，不参与问答检索。
            if doc["page_count"] > 200 and "--include-long" not in sys.argv:
                skipped += 1
                print(f"  {doc['title'][:40]:42s} 跳过（{doc['page_count']} 页超大文档）")
                continue
            try:
                r = client.post(f"/api/documents/{doc['doc_id']}/index")
                print(f"  {doc['title'][:40]:42s} -> {r.json().get('chunks')} 块")
            except Exception as exc:  # noqa: BLE001
                print(f"  {doc['title'][:40]:42s} 索引失败: {exc}")
        if skipped:
            print(f"（{skipped} 篇超大文档未建索引；需要时加 --include-long）")

        graph = client.get("/api/graph").json()
        print(f"\n图谱: {graph['stats']['nodes']} 节点 / {graph['stats']['edges']} 边")
        print("演示数据就绪。")


if __name__ == "__main__":
    main()
