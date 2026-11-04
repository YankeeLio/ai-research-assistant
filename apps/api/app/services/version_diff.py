"""版本差异：给出 v1 → v7 这类修订的**结构化**描述，而不是一句"内容有变化"。

做法：以章节为对齐单位，先按标题做模糊匹配，再在章节内按句子集合求增删，
最后汇总成"新增/删除/修改了哪些节、正文增加了多少、参考文献变化"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..models.schema import ParsedDocument


@dataclass
class SectionDelta:
    title: str
    status: str  # added | removed | modified | unchanged
    similarity: float = 0.0
    added_sentences: int = 0
    removed_sentences: int = 0
    note: str = ""


@dataclass
class VersionDiff:
    old_id: str
    new_id: str
    old_label: str
    new_label: str
    similarity: float
    sections: list[SectionDelta] = field(default_factory=list)
    stats: dict[str, object] = field(default_factory=dict)
    summary: str = ""


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", text.lower())


def _sentences(text: str) -> set[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return {_norm(p) for p in parts if len(p.strip()) > 30}


def _section_text(parsed: ParsedDocument) -> list[tuple[str, str]]:
    """按标题切分正文，返回 [(章节标题, 该节正文)]。"""
    out: list[tuple[str, list[str]]] = []
    current_title = "（正文开头）"
    current: list[str] = []
    depths: list[int] = []

    for block in parsed.blocks:
        if block.kind in ("heading", "title"):
            level = block.level or 1
            # 只在一级章节处切分，避免小节把正文切得太碎
            if level == 1 and current:
                out.append((current_title, current))
                current = []
            if level == 1:
                current_title = block.text
            depths.append(level)
            continue
        if block.kind == "paragraph":
            current.append(block.text)
    if current:
        out.append((current_title, current))
    return [(title, " ".join(texts)) for title, texts in out]


def diff_parsed(old: ParsedDocument, new: ParsedDocument) -> VersionDiff:
    old_sections = _section_text(old)
    new_sections = _section_text(new)

    old_keys = [(title, _norm(title)) for title, _ in old_sections]
    used_old: set[int] = set()
    deltas: list[SectionDelta] = []

    for title, body in new_sections:
        key = _norm(title)
        best_i, best_score = -1, 0.0
        for i, (_, old_key) in enumerate(old_keys):
            if i in used_old:
                continue
            score = SequenceMatcher(None, key, old_key).ratio()
            if score > best_score:
                best_i, best_score = i, score

        if best_i >= 0 and best_score >= 0.8:
            used_old.add(best_i)
            old_body = old_sections[best_i][1]
            old_sents, new_sents = _sentences(old_body), _sentences(body)
            added = len(new_sents - old_sents)
            removed = len(old_sents - new_sents)
            sim = SequenceMatcher(None, _norm(old_body), _norm(body)).ratio()
            status = "modified" if (added or removed) else "unchanged"
            deltas.append(
                SectionDelta(
                    title=title,
                    status=status,
                    similarity=round(sim, 3),
                    added_sentences=added,
                    removed_sentences=removed,
                )
            )
        else:
            deltas.append(
                SectionDelta(title=title, status="added", added_sentences=len(_sentences(body)))
            )

    for i, (title, _) in enumerate(old_sections):
        if i not in used_old:
            deltas.append(SectionDelta(title=title, status="removed"))

    stats: dict[str, object] = {
        "page_count": [old.stats.page_count if old.stats else 0, new.stats.page_count if new.stats else 0],
        "char_count": [old.stats.char_count if old.stats else 0, new.stats.char_count if new.stats else 0],
        "reference_count": [
            old.stats.reference_count if old.stats else 0,
            new.stats.reference_count if new.stats else 0,
        ],
        "table_count": [old.stats.table_count if old.stats else 0, new.stats.table_count if new.stats else 0],
        "formula_block_count": [
            old.stats.formula_block_count if old.stats else 0,
            new.stats.formula_block_count if new.stats else 0,
        ],
    }
    overall = SequenceMatcher(
        None,
        _norm(" ".join(b for _, b in old_sections)),
        _norm(" ".join(b for _, b in new_sections)),
    ).ratio()

    added = [d for d in deltas if d.status == "added"]
    removed = [d for d in deltas if d.status == "removed"]
    modified = [d for d in deltas if d.status == "modified"]

    parts = [f"正文整体相似度 {overall:.1%}"]
    if added:
        parts.append(f"新增 {len(added)} 节（{'、'.join(d.title[:24] for d in added[:3])}）")
    if removed:
        parts.append(f"删除 {len(removed)} 节（{'、'.join(d.title[:24] for d in removed[:3])}）")
    if modified:
        top = sorted(modified, key=lambda d: -(d.added_sentences + d.removed_sentences))[:3]
        detail = "、".join(
            f"{d.title[:20]}(+{d.added_sentences}/-{d.removed_sentences})" for d in top
        )
        parts.append(f"修改 {len(modified)} 节，改动最大的是 {detail}")

    delta_chars = int(stats["char_count"][1]) - int(stats["char_count"][0])
    parts.append(f"正文 {delta_chars:+d} 字符")
    parts.append(
        f"参考文献 {stats['reference_count'][0]} → {stats['reference_count'][1]} 条，"
        f"表格 {stats['table_count'][0]} → {stats['table_count'][1]} 个"
    )

    return VersionDiff(
        old_id=old.doc_id,
        new_id=new.doc_id,
        old_label=old.file_name,
        new_label=new.file_name,
        similarity=round(overall, 4),
        sections=deltas,
        stats=stats,
        summary="；".join(parts) + "。",
    )
