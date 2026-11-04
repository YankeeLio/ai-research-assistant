"""写作与可视化探针：跑通 CSV→图表、框架生成、架构图脚本。"""

from __future__ import annotations

from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=300) as client:
        print("== CSV → 图表 ==")
        csv_path = Path("scripts/samples/model_bleu.csv")
        with csv_path.open("rb") as fh:
            resp = client.post(
                "/api/viz/chart",
                files={"file": (csv_path.name, fh, "text/csv")},
                params={"title": "BLEU scores across model families"},
            )
        print("status", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            print("type:", data["chart_type"], "url:", data["url"])
            print("caption:", data["caption"])
            png = client.get(data["url"])
            out = Path("assets/shots/chart_sample.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png.content)
            print("saved", out, len(png.content), "bytes")
        else:
            print(resp.text[:300])

        print("\n== 论文框架（模板模式，引用只来自库内）==")
        resp = client.post(
            "/api/writing/outline",
            json={"idea": "用检索增强的方法降低学术问答中的幻觉", "top_k": 4},
        )
        print("status", resp.status_code)
        if resp.status_code == 200:
            data = resp.json()
            print("mode:", data["mode"], "warnings:", data["warnings"])
            print(data["markdown"][:700])
            print("references:", [r["title"][:40] for r in data["references"]])
        else:
            print(resp.text[:300])

        print("\n== 架构图脚本 ==")
        resp = client.post(
            "/api/writing/diagram",
            json={"stages": ["PDF", "Parser", "Chunker", "Retriever", "LLM", "Answer"], "title": "SciLoom"},
        )
        data = resp.json()
        print(data["mermaid"])


if __name__ == "__main__":
    main()
