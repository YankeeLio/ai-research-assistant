"""局域引用图谱：从文献库的参考文献反向连边，做图论指标挖掘。

为什么是"反向"连边
------------------
每篇论文的 References 列出的是它**引用**的工作，所以边方向是 引用者 → 被引者。
读者关心的是"哪几篇是这个领域的基石"，那要看**入度**与 PageRank：被同组论文
反复引用的节点自然浮上来。

三类节点
--------
- `foundational`：入度高、PageRank 高 —— 被整个局域网络反复引用的基石论文；
- `derivative`：入度低、出度高 —— 主要引用别人、很少被引用，多为边缘/衍生工作；
- `bridge`：betweenness 高 —— 连接两个子群的桥，常常是跨方向的关键综述。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

import networkx as nx

from ..models.schema import ParsedDocument

TITLE_MATCH_THRESHOLD = 0.82


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())


def _norm_ref(text: str) -> str:
    """参考文献条目里前 90 个字符通常就是标题部分。"""
    return _norm_title(text[:90])


@dataclass
class Node:
    id: str
    label: str
    year: int | None = None
    in_library: bool = False
    degree_in: int = 0
    degree_out: int = 0
    pagerank: float = 0.0
    betweenness: float = 0.0
    role: str = "normal"  # foundational | derivative | bridge | normal
    page_count: int = 0


@dataclass
class Edge:
    source: str
    target: str
    kind: str = "external"  # internal（库内互引）| external（引向库外）


@dataclass
class CitationGraph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    stats: dict = field(default_factory=dict)


def _match_library(ref_text: str, docs: list[ParsedDocument]) -> ParsedDocument | None:
    """把一条参考文献匹配到库内文档。

    在**整条**参考文献里找标题串，而不是只看前 90 字符：作者-年份式条目
    （ACL 风格）的标题往往出现在作者列表之后，只看前缀会全部漏匹配。
    """
    ref_key = _norm_title(ref_text)
    if len(ref_key) < 20:
        return None
    arxiv_m = re.search(r"arxiv:\s?(\d{4}\.\d{4,5})", ref_text, re.I)
    for doc in docs:
        if arxiv_m and arxiv_m.group(1) in (doc.file_name or ""):
            return doc
        title_key = _norm_title(doc.title)
        if len(title_key) < 12:
            continue
        if title_key in ref_key:
            return doc
    return None


def build_graph(docs: list[ParsedDocument], max_external: int = 24) -> CitationGraph:
    graph = nx.DiGraph()
    library_ids = {d.doc_id: d for d in docs}

    for doc in docs:
        graph.add_node(
            doc.doc_id,
            label=doc.title or doc.file_name,
            year=_guess_year(doc),
            in_library=True,
            page_count=doc.stats.page_count if doc.stats else 0,
        )

    external_counter: dict[str, int] = {}
    external_labels: dict[str, str] = {}

    for doc in docs:
        for ref in doc.references:
            target = _match_library(ref.text, docs)
            if target is not None and target.doc_id != doc.doc_id:
                graph.add_edge(doc.doc_id, target.doc_id, kind="internal")
                continue
            # 库外文献：先按标题骨架聚合，再决定是否保留（避免几百个孤立点）
            key = _norm_ref(ref.text)[:60]
            if not key:
                continue
            external_counter[key] = external_counter.get(key, 0) + 1
            external_labels.setdefault(key, ref.text[:120])
            if external_counter[key] >= 2:  # 只保留被引用两次以上的外部工作
                graph.add_edge(doc.doc_id, f"ext:{key}", kind="external")

    # 补充外部节点属性：只保留被引用次数最多的前 N 个，否则图上全是孤立标签
    ranked = sorted(external_counter.items(), key=lambda kv: -kv[1])
    keep = [f"ext:{k}" for k, _c in ranked[:max_external]]
    for node_id in list(graph.nodes):
        if str(node_id).startswith("ext:") and node_id not in keep:
            graph.remove_node(node_id)

    for node_id in graph.nodes:
        if str(node_id).startswith("ext:"):
            graph.nodes[node_id]["label"] = external_labels.get(str(node_id)[4:], str(node_id))
            graph.nodes[node_id]["in_library"] = False
            graph.nodes[node_id]["year"] = None
            graph.nodes[node_id]["page_count"] = 0

    pagerank = nx.pagerank(graph, alpha=0.85) if graph.number_of_nodes() else {}
    betweenness = (
        nx.betweenness_centrality(graph.to_undirected()) if graph.number_of_nodes() else {}
    )

    nodes: list[Node] = []
    for node_id, attrs in graph.nodes(data=True):
        node = Node(
            id=str(node_id),
            label=attrs.get("label", str(node_id)),
            year=attrs.get("year"),
            in_library=bool(attrs.get("in_library")),
            degree_in=graph.in_degree(node_id),
            degree_out=graph.out_degree(node_id),
            pagerank=round(float(pagerank.get(node_id, 0.0)), 4),
            betweenness=round(float(betweenness.get(node_id, 0.0)), 4),
            page_count=int(attrs.get("page_count", 0)),
        )
        nodes.append(node)

    _classify(nodes)
    edges = [Edge(source=str(u), target=str(v), kind=d.get("kind", "external")) for u, v, d in graph.edges(data=True)]

    stats = {
        "documents": len(library_ids),
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "internal_edges": sum(1 for e in edges if e.kind == "internal"),
        "density": round(nx.density(graph), 4) if graph.number_of_nodes() > 1 else 0.0,
        "is_dag": nx.is_directed_acyclic_graph(graph),
        "components": nx.number_weakly_connected_components(graph) if graph.number_of_nodes() else 0,
    }
    return CitationGraph(nodes=nodes, edges=edges, stats=stats)


def _classify(nodes: list[Node]) -> None:
    """按入度/出度/中介度给出角色标签。阈值用分位数，避免绝对数值不通用。"""
    if not nodes:
        return
    indeg = sorted(n.degree_in for n in nodes)
    outdeg = sorted(n.degree_out for n in nodes)
    betw = sorted(n.betweenness for n in nodes)
    in_hi = indeg[int(len(indeg) * 0.8)] if len(indeg) > 3 else indeg[-1]
    out_hi = outdeg[int(len(outdeg) * 0.8)] if len(outdeg) > 3 else outdeg[-1]
    betw_hi = betw[int(len(betw) * 0.85)] if len(betw) > 3 else betw[-1]

    for node in nodes:
        if node.degree_in >= max(2, in_hi) and node.pagerank > 0:
            node.role = "foundational"
        elif node.betweenness >= betw_hi and node.betweenness > 0 and node.degree_in >= 2:
            node.role = "bridge"
        elif node.degree_out >= max(2, out_hi) and node.degree_in <= 1:
            node.role = "derivative"


def _guess_year(doc: ParsedDocument) -> int | None:
    years = [r.year for r in doc.references if r.year]
    if years:
        return max(years)
    return None


def to_payload(graph: CitationGraph) -> dict:
    return {
        "nodes": [asdict(n) for n in graph.nodes],
        "edges": [asdict(e) for e in graph.edges],
        "stats": graph.stats,
        "foundational": [
            {"id": n.id, "label": n.label, "pagerank": n.pagerank, "degree_in": n.degree_in}
            for n in sorted(graph.nodes, key=lambda n: -n.pagerank)[:5]
            if n.role == "foundational"
        ],
    }
