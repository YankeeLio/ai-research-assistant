"""局域综述生成：把图谱结构翻译成人能读的一段话。

没有大模型时用结构化模板：基石论文、演进链条、分支方向、研究空白。
接了大模型后可以在此之上做润色，但**骨架必须来自图谱统计**，否则又会变成
"让模型编一段综述"——那正是本赛项要避免的。
"""

from __future__ import annotations

from ..models.schema import ParsedDocument
from .graph import CitationGraph


def generate(graph: CitationGraph, docs: list[ParsedDocument]) -> dict:
    nodes = graph.nodes
    foundational = sorted(
        [n for n in nodes if n.role == "foundational"], key=lambda n: -n.pagerank
    )[:5]
    bridges = sorted([n for n in nodes if n.role == "bridge"], key=lambda n: -n.betweenness)[:3]
    derivative = sorted(
        [n for n in nodes if n.role == "derivative"], key=lambda n: -n.degree_out
    )[:5]

    library = [n for n in nodes if n.in_library]
    edges_internal = [e for e in graph.edges if e.kind == "internal"]

    paragraphs: list[str] = []
    paragraphs.append(
        f"本次分析覆盖 {len(library)} 篇库内文献、{graph.stats['nodes']} 个节点、"
        f"{graph.stats['edges']} 条引用关系（其中国库内部互引 {len(edges_internal)} 条），"
        f"图密度 {graph.stats['density']}，弱连通分量 {graph.stats['components']} 个。"
    )

    if foundational:
        names = "、".join(f"《{_short(n.label)}》" for n in foundational)
        paragraphs.append(
            f"以 PageRank 与入度衡量，{names} 构成了这一局域网络的基石：它们被同组文献反复引用，"
            f"是后续工作的共同前提。其中《{_short(foundational[0].label)}》的 PageRank 最高"
            f"（{foundational[0].pagerank:.3f}，被引 {foundational[0].degree_in} 次）。"
        )

    if bridges:
        names = "、".join(f"《{_short(n.label)}》" for n in bridges)
        paragraphs.append(
            f"中介中心性最高的是 {names}，它们在图上位于不同子群的连接处，"
            f"通常对应跨方向的综述或方法迁移，是理解分支演化的入口。"
        )

    if derivative:
        names = "、".join(f"《{_short(n.label)}》" for n in derivative)
        paragraphs.append(
            f"{names} 等节点出度高而入度低，属于衍生工作：它们大量引用前人成果，"
            f"但尚未成为被后续工作反复依赖的基础，可作为追踪前沿的观察点。"
        )

    years = sorted({n.year for n in library if n.year})
    if len(years) >= 2:
        paragraphs.append(
            f"时间跨度 {years[0]}–{years[-1]}，引用关系的方向基本符合时间顺序"
            + ("（图为有向无环图）。" if graph.stats["is_dag"] else "（存在少量回边，多为修订版互引）。")
        )

    gaps = _future_work(docs)
    return {
        "summary": "\n\n".join(paragraphs),
        "stats": graph.stats,
        "foundational": [
            {"id": n.id, "label": n.label, "pagerank": n.pagerank, "degree_in": n.degree_in}
            for n in foundational
        ],
        "bridges": [{"id": n.id, "label": n.label, "betweenness": n.betweenness} for n in bridges],
        "derivative": [{"id": n.id, "label": n.label, "degree_out": n.degree_out} for n in derivative],
        "future_work": gaps,
    }


def _future_work(docs: list[ParsedDocument]) -> list[dict]:
    """从各篇论文的 Future Work / Conclusion 中抽取句子，作为待探索方向。"""
    out: list[dict] = []
    for doc in docs:
        for block in doc.blocks:
            text = block.text
            if not text:
                continue
            lowered = text.lower()
            if not any(k in lowered for k in ("future work", "we leave", "remains open", "future research")):
                continue
            out.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title or doc.file_name,
                    "page": block.page,
                    "text": text[:400],
                }
            )
            break
    return out[:6]


def _short(label: str, limit: int = 40) -> str:
    label = label.strip()
    return label if len(label) <= limit else label[:limit] + "…"
