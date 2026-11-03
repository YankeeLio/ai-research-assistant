"""抗幻觉问答：检索取证 → 约束生成 → 引用校验。

三道闸门
--------
1. **只许用证据**：提示词把模型限制在检索片段内，并要求逐句标注 [cN]。
2. **引用必须真实存在**：生成后解析引用编号，凡不在本次证据集合内的一律剔除
   并记入 warnings——这是防"编造出处"的最后一道硬约束。
3. **无证据即拒答**：模型未给出任何引用时，回答被标记为 `ungrounded`，
   前端会显式提示"未绑定原文"，而不是把它当成可信答案。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from collections.abc import AsyncIterator

from ..core.config import get_settings
from .chunking import Chunk
from .llm import LLMClient, LLMNotConfigured
from .retrieval import DocumentIndex, get_embedder, tokenize

logger = logging.getLogger(__name__)

CITE_TAG_RE = re.compile(r"\[(c[0-9a-zA-Z]{4,16})\]")

SYSTEM_PROMPT = """你是严谨的学术文献阅读助手。你只能依据 <证据> 中的片段作答。

规则：
1. 每个事实性陈述必须以来源编号结尾，格式 [c3]；多来源写成 [c1][c7]。
2. 证据不足时，只回答"现有材料不足以回答该问题"，并说明缺少什么信息，禁止推测或使用外部知识。
3. 涉及数字、超参数、硬件、指标时，必须原样抄录原文数值与单位，不得换算或四舍五入。
4. 不得引用 <证据> 中不存在编号；不得编造参考文献条目。
5. 用中文回答，术语、公式与指标名保留英文原文。
"""


@dataclass
class Evidence:
    chunk_id: str
    page: int
    section: str
    text: str
    score: float


def load_index(doc_id: str) -> DocumentIndex | None:
    settings = get_settings()
    directory = settings.docs_dir / doc_id / "index"
    try:
        index = DocumentIndex.load(doc_id, directory)
    except (TypeError, KeyError, ValueError) as exc:
        # 索引结构与代码版本不一致时直接重建，而不是让接口 500
        logger.warning("索引格式不兼容（%s），将重建", exc)
        return None
    if index is None:
        return None
    meta_path = directory / "meta.json"
    current = get_embedder().name
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("embedder") != current:
            logger.info("向量模型由 %s 变为 %s，索引需重建", meta.get("embedder"), current)
            return None
    return index


def build_index(doc_id: str, chunks: list[Chunk]) -> DocumentIndex:
    settings = get_settings()
    embedder = get_embedder()
    index = DocumentIndex.build(doc_id, chunks, embedder)
    directory = settings.docs_dir / doc_id / "index"
    index.save(directory)
    (directory / "meta.json").write_text(
        json.dumps({"embedder": embedder.name, "dim": embedder.dim, "chunks": len(chunks)}),
        encoding="utf-8",
    )
    return index


def ensure_index(doc_id: str) -> DocumentIndex | None:
    """惰性建索引：上传只做解析，索引在第一次检索时构建，避免阻塞上传。"""
    index = load_index(doc_id)
    if index is not None:
        return index

    from ..core import db
    from ..models.schema import ParsedDocument
    from .chunking import chunk_document

    payload = db.load_parsed(doc_id)
    if payload is None:
        return None
    parsed = ParsedDocument.model_validate(payload)
    settings = get_settings()
    chunks = chunk_document(parsed, size=settings.chunk_size, overlap=settings.chunk_overlap)
    return build_index(doc_id, chunks)


def _format_evidence(chunks: list[tuple[Chunk, float]]) -> tuple[str, list[Evidence]]:
    blocks: list[str] = []
    evidence: list[Evidence] = []
    for i, (chunk, score) in enumerate(chunks, start=1):
        tag = f"c{i}"  # 提示词里用短编号，避免模型抄错长哈希
        evidence.append(
            Evidence(
                chunk_id=tag,
                page=chunk.page,
                section=chunk.section_path,
                text=chunk.text,
                score=round(score, 4),
            )
        )
        blocks.append(f"[{tag}] (p.{chunk.page + 1} · {chunk.section_path or '正文'})\n{chunk.text}")
    return "\n\n".join(blocks), evidence


def _validate(answer: str, evidence: list[Evidence]) -> tuple[str, list[str]]:
    allowed = {e.chunk_id for e in evidence}
    unknown = {m for m in CITE_TAG_RE.findall(answer) if m not in allowed}
    cleaned = CITE_TAG_RE.sub(lambda m: "" if m.group(1) in unknown else m.group(0), answer)
    return cleaned, sorted(unknown)


def _extractive(question: str, chunks: list[tuple[Chunk, float]]) -> str:
    """无模型时的抽取式回答：从最相关块里挑与问题重合度最高的句子。"""
    q_tokens = set(tokenize(question))
    best: list[tuple[float, str, str]] = []
    for chunk, _score in chunks[:3]:
        for sentence in re.split(r"(?<=[.!?。！？])\s+", chunk.text):
            if len(sentence) < 20:
                continue
            overlap = len(q_tokens & set(tokenize(sentence))) / (len(q_tokens) or 1)
            best.append((overlap, sentence.strip(), chunk.id))
    best.sort(key=lambda x: -x[0])
    if not best or best[0][0] == 0:
        return "现有材料不足以回答该问题。"
    tag_map = {c.id: f"c{i}" for i, (c, _s) in enumerate(chunks, start=1)}
    picked = [f"{s} [{tag_map[cid]}]" for score, s, cid in best[:3] if score > 0]
    return "（抽取式回答，未调用大模型）\n" + " ".join(picked)


async def answer(doc_id: str, question: str, top_k: int = 8) -> dict:
    index = load_index(doc_id)
    if index is None:
        return {
            "answer": "",
            "evidence": [],
            "warnings": ["index_missing"],
            "mode": "none",
        }

    chunks = index.search(question, top_k=top_k)
    if not chunks:
        return {"answer": "现有材料不足以回答该问题。", "evidence": [], "warnings": ["no_hits"], "mode": "none"}

    context, evidence = _format_evidence(chunks)
    client = LLMClient()
    warnings: list[str] = []
    if client.available:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"<证据>\n{context}\n</证据>\n\n问题：{question}"},
        ]
        try:
            raw = await client.complete(messages)
            mode = "llm"
        except Exception as exc:  # noqa: BLE001 - 模型故障时回落到抽取式
            logger.warning("模型调用失败，回落抽取式：%s", exc)
            raw, mode = _extractive(question, chunks), "extractive"
            warnings.append(f"llm_failed: {exc}")
    else:
        raw, mode = _extractive(question, chunks), "extractive"
        warnings.append("llm_not_configured")

    cleaned, unknown = _validate(raw, evidence)
    if unknown:
        warnings.append(f"unknown_citations_removed: {','.join(unknown)}")
    if mode == "llm" and not CITE_TAG_RE.search(cleaned):
        warnings.append("ungrounded: 回答未绑定任何证据")

    return {
        "answer": cleaned,
        "evidence": [asdict(e) for e in evidence],
        "warnings": warnings,
        "mode": mode,
    }


async def stream_answer(doc_id: str, question: str, top_k: int = 8) -> AsyncIterator[str]:
    """SSE 流：先发证据，再发 token，最后发校验结果。"""
    index = load_index(doc_id)
    if index is None:
        yield _sse({"type": "error", "message": "index_missing"})
        return

    chunks = index.search(question, top_k=top_k)
    context, evidence = _format_evidence(chunks)
    yield _sse({"type": "evidence", "items": [asdict(e) for e in evidence]})

    client = LLMClient()
    if not client.available:
        text = _extractive(question, chunks)
        yield _sse({"type": "delta", "text": text})
        yield _sse({"type": "done", "warnings": ["llm_not_configured"], "mode": "extractive"})
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"<证据>\n{context}\n</证据>\n\n问题：{question}"},
    ]
    raw_parts: list[str] = []
    try:
        async for piece in client.stream(messages):
            raw_parts.append(piece)
            yield _sse({"type": "delta", "text": piece})
    except LLMNotConfigured:
        yield _sse({"type": "error", "message": "llm_not_configured"})
        return
    except Exception as exc:  # noqa: BLE001
        yield _sse({"type": "error", "message": str(exc)[:200]})
        return

    answer_text, unknown = _validate("".join(raw_parts), evidence)
    warnings = [f"unknown_citations_removed: {','.join(unknown)}"] if unknown else []
    if not CITE_TAG_RE.search(answer_text):
        warnings.append("ungrounded: 回答未绑定任何证据")
    yield _sse({"type": "done", "warnings": warnings, "mode": "llm"})


def _sse(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
