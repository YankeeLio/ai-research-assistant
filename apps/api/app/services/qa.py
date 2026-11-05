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
from dataclasses import asdict, dataclass, field
from collections.abc import AsyncIterator

from ..core.config import get_settings
from .chunking import Chunk
from .llm import LLMClient, LLMNotConfigured
from .retrieval import DocumentIndex, get_embedder, tokenize

logger = logging.getLogger(__name__)

# 证据编号是 c1、c2 …（短编号，模型不易抄错），匹配放宽到 1-3 位数字。
# 早期写成 c[0-9a-zA-Z]{4,16}，短编号永远匹配不上，导致引用校验形同虚设。
CITE_TAG_RE = re.compile(r"\[(c\d{1,3})\]")

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
    block_ids: list[str] = field(default_factory=list)
    doc_id: str = ""
    title: str = ""


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


def _format_evidence(
    chunks: list[tuple[Chunk, float]], doc_titles: dict[str, str] | None = None
) -> tuple[str, list[Evidence]]:
    blocks: list[str] = []
    evidence: list[Evidence] = []
    for i, (chunk, score) in enumerate(chunks, start=1):
        tag = f"c{i}"  # 提示词里用短编号，避免模型抄错长哈希
        title = (doc_titles or {}).get(chunk.doc_id, "")
        evidence.append(
            Evidence(
                chunk_id=tag,
                page=chunk.page,
                section=chunk.section_path,
                text=chunk.text,
                score=round(score, 4),
                block_ids=chunk.block_ids,
                doc_id=chunk.doc_id,
                title=title,
            )
        )
        source = f"《{title[:40]}》" if title else ""
        blocks.append(
            f"[{tag}] {source}(p.{chunk.page + 1} · {chunk.section_path or '正文'})\n{chunk.text}"
        )
    return "\n\n".join(blocks), evidence


def _validate(answer: str, evidence: list[Evidence]) -> tuple[str, list[str]]:
    allowed = {e.chunk_id for e in evidence}
    unknown = {m for m in CITE_TAG_RE.findall(answer) if m not in allowed}
    cleaned = CITE_TAG_RE.sub(lambda m: "" if m.group(1) in unknown else m.group(0), answer)
    return cleaned, sorted(unknown)


NUMERIC_QUESTION_RE = re.compile(r"多少|几|数量|how many|how much|number of|尺寸|dimension", re.I)


def _extractive(question: str, chunks: list[tuple[Chunk, float]]) -> str:
    """无模型时的抽取式回答：从检索到的块里挑最贴题的句子。

    问数量类问题时给"含数字的句子"加权——这不是炫技，而是因为跨语言提问时
    中文词与英文句子几乎没有字面重合，只按词重合度挑，会选中同样提到 GPU
    但并没有给出数量的句子。
    """
    q_tokens = set(tokenize(question))
    want_number = bool(NUMERIC_QUESTION_RE.search(question))
    best: list[tuple[float, str, str]] = []
    for chunk, _score in chunks[:5]:
        for sentence in re.split(r"(?<=[.!?。！？])\s+", chunk.text):
            if len(sentence) < 20:
                continue
            overlap = len(q_tokens & set(tokenize(sentence))) / (len(q_tokens) or 1)
            score = overlap
            if want_number and re.search(r"\d", sentence):
                score += 0.35
            best.append((score, sentence.strip(), chunk.id))
    best.sort(key=lambda x: -x[0])
    if not best or best[0][0] <= 0:
        return "现有材料不足以回答该问题。"
    tag_map = {c.id: f"c{i}" for i, (c, _s) in enumerate(chunks, start=1)}
    picked: list[str] = []
    seen: set[str] = set()
    for score, sentence, cid in best:
        if score <= 0 or sentence in seen:
            continue
        seen.add(sentence)
        picked.append(f"{sentence} [{tag_map[cid]}]")
        if len(picked) >= 2:
            break
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
        yield sse({"type": "error", "message": "index_missing"})
        return

    chunks = index.search(question, top_k=top_k)
    context, evidence = _format_evidence(chunks)
    yield sse({"type": "evidence", "items": [asdict(e) for e in evidence]})

    client = LLMClient()
    if not client.available:
        text = _extractive(question, chunks)
        yield sse({"type": "delta", "text": text})
        yield sse({"type": "done", "warnings": ["llm_not_configured"], "mode": "extractive"})
        return

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"<证据>\n{context}\n</证据>\n\n问题：{question}"},
    ]
    raw_parts: list[str] = []
    try:
        async for piece in client.stream(messages):
            raw_parts.append(piece)
            yield sse({"type": "delta", "text": piece})
    except LLMNotConfigured:
        yield sse({"type": "error", "message": "llm_not_configured"})
        return
    except Exception as exc:  # noqa: BLE001
        yield sse({"type": "error", "message": str(exc)[:200]})
        return

    answer_text, unknown = _validate("".join(raw_parts), evidence)
    warnings = [f"unknown_citations_removed: {','.join(unknown)}"] if unknown else []
    if not CITE_TAG_RE.search(answer_text):
        warnings.append("ungrounded: 回答未绑定任何证据")
    yield sse({"type": "done", "warnings": warnings, "mode": "llm"})


def sse(payload: dict) -> str:
    return f"event: message\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


COMPARE_PROMPT = """你是严谨的学术文献对比助手。用户给出多篇论文，要求对比。

规则：
1. 只能依据 <证据> 作答，每条结论必须标注来源编号 [cN]；同一结论涉及多篇时并列标注，如 [c1][c5]。
2. 优先按"维度"组织回答（例如结构、训练方式、数据规模、指标），而不是逐篇复述。
3. 明确指出承袭关系与差异点；如果某篇论文的证据不足以支撑某个维度，直接写"该论文未提供相关信息"。
4. 不得引入证据之外的知识；不得编造数值。
5. 中文回答，模型名、指标名保留英文。
"""


def compare(doc_ids: list[str], question: str, per_doc: int = 4) -> dict:
    """跨文献对比：每篇各取若干片段，统一编号后交给模型做维度化对比。"""
    from ..core import db

    titles: dict[str, str] = {}
    merged: list[tuple[Chunk, float]] = []
    missing: list[str] = []

    for doc_id in doc_ids:
        index = ensure_index(doc_id)
        if index is None:
            missing.append(doc_id)
            continue
        row = db.get_document(doc_id) or {}
        titles[doc_id] = row.get("title") or row.get("file_name") or doc_id
        merged.extend(index.search(question, top_k=per_doc))

    if not merged:
        return {
            "answer": "",
            "evidence": [],
            "warnings": ["no_index: " + ",".join(missing)] if missing else ["no_hits"],
            "mode": "none",
            "docs": [],
        }

    context, evidence = _format_evidence(merged, titles)
    client = LLMClient()
    warnings: list[str] = []
    if missing:
        warnings.append("index_missing: " + ",".join(missing))

    if not client.available:
        lines = []
        for ev in evidence:
            lines.append(f"《{ev.title[:36]}》p.{ev.page + 1}：{ev.text[:160]}… [{ev.chunk_id}]")
        return {
            "answer": "（未配置模型，仅列出各篇的相关段落，便于人工比对）\n" + "\n\n".join(lines),
            "evidence": [asdict(e) for e in evidence],
            "warnings": warnings + ["llm_not_configured"],
            "mode": "evidence-only",
            "docs": [{"doc_id": d, "title": titles.get(d, d)} for d in doc_ids if d in titles],
        }

    messages = [
        {"role": "system", "content": COMPARE_PROMPT},
        {
            "role": "user",
            "content": f"<证据>\n{context}\n</证据>\n\n对比问题：{question}",
        },
    ]
    try:
        # 用 chat 模型而不是 reasoner：对比回答较长，reasoner 单次 30-60 s，
        # 会被前端/反代的 30 s 超时掐断，表现为 500
        raw = client.complete_sync(messages)
        mode = "llm"
    except Exception as exc:  # noqa: BLE001
        logger.warning("对比生成失败: %s", exc)
        raw = "（模型调用失败，仅列出证据供人工比对）"
        mode = "evidence-only"
        warnings.append(f"llm_failed: {exc}")

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
        "docs": [{"doc_id": d, "title": titles.get(d, d)} for d in doc_ids if d in titles],
    }
