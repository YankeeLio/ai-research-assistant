"""写作辅助：论文框架 + 无幻觉参考文献 + 架构图脚本。

**无幻觉**在这里是硬约束，不是提示词里的一句请求：

1. 参考文献只能来自本地文献库。模型若引用了编号 `[7]` 而实际只提供了 5 条，
   该编号会被剔除并记录到 warnings；
2. 每个被引用的条目都带 `doc_id`，前端可点回原文；
3. 没有配置模型时不假装生成——直接返回结构化模板，并把 `mode` 标为 `template`，
   用户看到的是"骨架 + 真实文献"，而不是一段编出来的 Introduction。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import numpy as np

from ..models.schema import ParsedDocument
from .llm import LLMClient
from .retrieval import get_embedder

logger = logging.getLogger(__name__)

CITE_RE = re.compile(r"\[(\d{1,2})\]")

SYSTEM_PROMPT = """你是学术写作助手。根据用户给出的研究想法和参考文献列表撰写论文框架。

硬性规则：
1. 只能引用 <参考文献> 中列出的条目，用 [n] 标注，n 必须是列表中的编号；
2. 不得编造参考文献、作者、年份、实验数值；
3. 无法从给定文献支撑的论断，用"待补充实验"占位；
4. 输出 Markdown，包含 Abstract、Introduction、Related Work 三节；
5. 中文撰写，术语保留英文。
"""


@dataclass
class Citation:
    index: int
    doc_id: str
    title: str
    authors: list[str]
    year: int | None
    page: int

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "doc_id": self.doc_id,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "page": self.page,
        }

    def format(self) -> str:
        authors = ", ".join(self.authors[:3]) + (" 等" if len(self.authors) > 3 else "")
        year = f" ({self.year})" if self.year else ""
        prefix = f"{authors}. " if authors.strip() else ""
        return f"[{self.index}] {prefix}{self.title}{year}."


def select_references(idea: str, docs: list[ParsedDocument], top_k: int = 5) -> list[Citation]:
    """按与 idea 的语义相似度挑库内文献，保证"引用的都是读过的"。"""
    if not docs:
        return []
    texts = [f"{d.title}. {(d.abstract or '')[:500]}" for d in docs]
    embeddings = get_embedder().encode(texts)
    query = get_embedder().encode([idea])[0]
    scores = embeddings @ query
    order = np.argsort(-scores)[:top_k]

    citations: list[Citation] = []
    for i, idx in enumerate(order, start=1):
        doc = docs[int(idx)]
        year = None
        if doc.references:
            years = [r.year for r in doc.references if r.year]
            year = max(years) if years else None
        citations.append(
            Citation(
                index=i,
                doc_id=doc.doc_id,
                title=doc.title or doc.file_name,
                authors=doc.authors,
                year=year,
                page=0,
            )
        )
    return citations


def build_outline(idea: str, docs: list[ParsedDocument], top_k: int = 5) -> dict:
    citations = select_references(idea, docs, top_k=top_k)
    client = LLMClient()

    if not client.available:
        return _template_outline(idea, citations, reason="llm_not_configured")

    refs_block = "\n".join(c.format() for c in citations)
    prompt = (
        f"<研究想法>\n{idea}\n</研究想法>\n\n"
        f"<参考文献>\n{refs_block}\n</参考文献>\n\n"
        "请据此写出论文框架（Abstract / Introduction / Related Work），不超过 800 字。"
    )
    try:
        text = client.complete(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except Exception as exc:  # noqa: BLE001 - 模型故障时回落模板
        logger.warning("框架生成失败，回落模板: %s", exc)
        return _template_outline(idea, citations, reason=f"llm_failed: {exc}")

    cleaned, unknown = _validate_citations(text, len(citations))
    warnings = [f"unknown_citations_removed: {','.join(map(str, unknown))}"] if unknown else []
    return {
        "mode": "llm",
        "idea": idea,
        "markdown": cleaned,
        "references": [c.to_dict() for c in citations],
        "warnings": warnings,
    }


def _validate_citations(text: str, allowed_count: int) -> tuple[str, list[int]]:
    """剔除越界引用编号：模型最容易在这里编造出处。"""
    unknown = {
        int(m.group(1)) for m in CITE_RE.finditer(text) if not 1 <= int(m.group(1)) <= allowed_count
    }
    if not unknown:
        return text, []
    cleaned = CITE_RE.sub(
        lambda m: "" if not 1 <= int(m.group(1)) <= allowed_count else m.group(0), text
    )
    return cleaned, sorted(unknown)


def _template_outline(idea: str, citations: list[Citation], reason: str) -> dict:
    refs = "\n".join(f"{i}. {c.title}" for i, c in enumerate(citations, start=1))
    cites = " ".join(f"[{c.index}]" for c in citations) or "[待补充]"
    markdown = f"""# {idea.strip()[:60]}

## Abstract

针对「{idea.strip()}」这一问题，本文提出待补充的方法框架。已有工作表明该方向仍有改进空间 {cites}。
（本节为结构化模板：接入大模型后将根据文献库自动扩写，且只允许引用下方 References 中的条目。）

## 1 Introduction

- **研究背景**：待补充（建议引用 {cites} 中的 1-2 篇说明问题来源）。
- **现有方法的不足**：待补充（建议结合库内文献的实验设置对比）。
- **本文贡献**：1) 待补充；2) 待补充；3) 待补充。

## 2 Related Work

{(''.join(f'- {c.format()}{chr(10)}' for c in citations)) if citations else '- 库内暂无可用文献，请先导入 PDF'}

## References

{refs if refs else '（空：先在文献库中导入论文）'}
"""
    return {
        "mode": "template",
        "idea": idea,
        "markdown": markdown,
        "references": [c.to_dict() for c in citations],
        "warnings": [reason],
    }


def build_diagram(stages: list[str], title: str = "Architecture") -> dict:
    """从"阶段列表"生成三种可直接编译的拓扑图脚本。

    不追求任意拓扑的自动排版——那需要真正的布局引擎；这里给的是**可交付**的
    脚本：用户改两行节点就能用，且 Mermaid 在浏览器里能立刻预览。
    """
    stages = [s.strip() for s in stages if s.strip()] or ["Input", "Encoder", "Decoder", "Output"]
    nodes = [f"{_ident(i, s)}[{_escape(s)}]" for i, s in enumerate(stages)]

    mermaid_lines = ["flowchart LR"]
    for i, node in enumerate(nodes):
        mermaid_lines.append(f"    {node}")
    for i in range(len(nodes) - 1):
        mermaid_lines.append(f"    {_ident(i, stages[i])} --> {_ident(i + 1, stages[i + 1])}")
    mermaid = "\n".join(mermaid_lines)

    tikz_nodes = "\n".join(
        f"  \\node[box] (n{i}) {{{_escape(stages[i])}}};" for i in range(len(stages))
    )
    tikz_edges = "\n".join(f"  \\draw[->] (n{i}) -- (n{i + 1});" for i in range(len(stages) - 1))
    tikz = f"""\\begin{{tikzpicture}}[node distance=12mm, every node/.style={{font=\\small}}]
  \\tikzset{{box/.style={{draw, rounded corners=2pt, minimum height=9mm, minimum width=24mm, align=center}}}}
{tikz_nodes}
{tikz_edges}
\\end{{tikzpicture}}"""

    dot_edges = "\n".join(
        f'  "{_escape(stages[i])}" -> "{_escape(stages[i + 1])}";' for i in range(len(stages) - 1)
    )
    dot = f'digraph "{title}" {{\n  rankdir=LR;\n  node [shape=box, style=rounded];\n{dot_edges}\n}}'

    return {"title": title, "stages": stages, "mermaid": mermaid, "tikz": tikz, "graphviz": dot}


def _ident(index: int, stage: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "", stage)[:12] or f"n{index}"
    return f"{slug.lower()}{index}"


def _escape(text: str) -> str:
    return text.replace('"', "'").replace("\n", " ")
