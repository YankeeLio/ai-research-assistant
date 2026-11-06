"""评审自查：按 docs/DEMO.md 的路径把六大模块跑一遍，输出 PASS/FAIL 与耗时。

用法:
    python scripts/reviewer_walkthrough.py            # 全部检查
    python scripts/reviewer_walkthrough.py --keep-v1  # 保留去重演示中上传的 v1

设计意图：这个脚本模拟评审的点击顺序，任何一步 4xx/5xx 或关键字段缺失都算不合格。
比"截图看起来正常"更可信，也能在部署到服务器后直接对着线上地址跑。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("http") else "http://127.0.0.1:8000"
PDF_DIR = Path(__file__).resolve().parents[1] / "pdf"
KEEP_V1 = "--keep-v1" in sys.argv

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  —— {detail}" if detail else ""))


def main() -> int:
    with httpx.Client(base_url=BASE, timeout=900) as client:
        print(f"目标: {BASE}\n")

        # 1. 健康检查
        t = time.time()
        health = client.get("/api/health").json()
        check("健康检查", health.get("status") == "ok", f"{time.time() - t:.1f}s")

        # 2. 文献库
        docs = client.get("/api/documents").json()
        check("文献库非空", len(docs) >= 5, f"{len(docs)} 篇")
        titles = {d["title"][:30]: d for d in docs}
        attn = next((d for d in docs if d["title"].startswith("Attention") and not d["is_scanned"]), None)
        bert = next((d for d in docs if d["title"].upper().startswith("BERT")), None)
        gpt3 = next((d for d in docs if "Few-Shot" in d["title"]), None)

        # 3. 去重（官方用例 A）
        v7 = PDF_DIR / "1706.03762v7.pdf"
        v1 = PDF_DIR / "1706.03762v1.pdf"
        if v7.exists() and v1.exists():
            with v7.open("rb") as fh:
                r = client.post("/api/documents/upload", files={"file": (v7.name, fh, "application/pdf")})
            dup_v7 = r.json()
            with v1.open("rb") as fh:
                r = client.post("/api/documents/upload", files={"file": (v1.name, fh, "application/pdf")})
            old = r.json()
            ok = old.get("duplicate_verdict") in ("same_work", "identical")
            check(
                "语义去重（v1 vs 库内 v7）",
                ok,
                f"{old.get('duplicate_verdict')} 相似度 {old.get('duplicate_similarity')}；建议 {old.get('duplicate_action')}",
            )
            if not KEEP_V1:
                client.delete(f"/api/documents/{old['doc_id']}")
                client.delete(f"/api/documents/{dup_v7['doc_id']}")

        # 4. 单篇问答（可回答）
        if attn:
            q = "训练用了多少块 GPU、什么型号？"
            t = time.time()
            r = client.post("/api/qa/ask", json={"doc_id": attn["doc_id"], "question": q})
            data = r.json()
            answer = data.get("answer", "")
            ok = ("P100" in answer) and ("[c" in answer)
            check("单篇问答+溯源", ok, f"{data.get('mode')} / {time.time() - t:.1f}s / 引用 {answer.count('[c')} 处")

        # 5. 拒答（抗幻觉）
        if gpt3:
            q = "训练时用了多少块 GPU、什么型号？"
            r = client.post("/api/qa/ask", json={"doc_id": gpt3["doc_id"], "question": q})
            data = r.json()
            answer = data.get("answer", "")
            ok = ("不足以" in answer) or ("没有给出" in answer) or ("未给出" in answer)
            check("证据不足时拒答", ok, answer[:48].replace("\n", " "))

        # 6. 跨文献对比
        if attn and bert:
            t = time.time()
            r = client.post(
                "/api/qa/compare",
                json={"doc_ids": [attn["doc_id"], bert["doc_id"]], "question": "BERT 与 Transformer Encoder 的承袭与差异？"},
            )
            data = r.json()
            ev = data.get("evidence", [])
            docs_in_ev = {e["doc_id"] for e in ev}
            ok = data.get("mode") == "llm" and len(docs_in_ev) >= 2 and "[c" in data.get("answer", "")
            check("跨文献对比", ok, f"{len(ev)} 条证据 / 覆盖 {len(docs_in_ev)} 篇 / {time.time() - t:.1f}s")

        # 7. 引用图谱与综述
        g = client.get("/api/graph").json()
        s = client.get("/api/graph/survey").json()
        check(
            "引用图谱",
            g["stats"]["nodes"] > 20 and g["stats"]["internal_edges"] > 5,
            f"{g['stats']['nodes']} 节点 / {g['stats']['edges']} 边",
        )
        check("自动综述", len(s.get("summary", "")) > 150, f"{len(s.get('summary', ''))} 字")

        # 8. arXiv 检索
        try:
            t = time.time()
            r = client.get("/api/arxiv/search", params={"q": "all:retrieval augmented generation", "max_results": 5})
            items = r.json().get("items", [])
            check("arXiv 检索与重排", r.status_code == 200 and len(items) > 0, f"{len(items)} 条 / {time.time() - t:.1f}s")
        except Exception as exc:  # noqa: BLE001 - 外网波动不算系统缺陷
            check("arXiv 检索与重排", False, f"网络异常: {exc}")

        # 9. 写作框架
        r = client.post("/api/writing/outline", json={"idea": "用检索增强降低学术问答幻觉", "top_k": 4})
        data = r.json()
        check(
            "无幻觉框架生成",
            len(data.get("references", [])) >= 3 and "Abstract" in data.get("markdown", ""),
            f"{data.get('mode')} / 引用 {len(data.get('references', []))} 篇",
        )

        # 10. CSV → 图表
        csv_path = Path(__file__).with_name("samples") / "model_bleu.csv"
        with csv_path.open("rb") as fh:
            r = client.post("/api/viz/chart", files={"file": (csv_path.name, fh, "text/csv")}, params={"title": "BLEU"})
        data = r.json()
        check(
            "CSV 学术图表与图注",
            r.status_code == 200 and len(data.get("caption", "")) > 80,
            f"{data.get('chart_type')} / 图注 {len(data.get('caption', ''))} 字",
        )

        # 11. 划词翻译
        t = time.time()
        r = client.post("/api/translate/selection", json={"text": "We trained our models on 8 NVIDIA P100 GPUs."})
        data = r.json()
        ok = r.status_code == 200 and any("\u4e00" <= ch <= "\u9fff" for ch in data.get("target", ""))
        check("划词翻译", ok, f"{data.get('mode')} / {time.time() - t:.1f}s")

        # 12. 架构图脚本
        r = client.post("/api/writing/diagram", json={"stages": ["PDF", "Parser", "Retriever", "LLM"], "title": "demo"})
        data = r.json()
        check(
            "架构图脚本生成",
            "flowchart" in data.get("mermaid", "") and "tikzpicture" in data.get("tikz", ""),
            "Mermaid + TikZ + Graphviz",
        )

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n结果：{passed}/{len(results)} 通过")
    if passed != len(results):
        print("未通过项：")
        for name, ok, detail in results:
            if not ok:
                print(f"  - {name}: {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
