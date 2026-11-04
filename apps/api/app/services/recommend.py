"""个性化推荐：把 arXiv 候选论文按"与本地文献库的相关性"排序。

打分不是拍脑袋的三项加权，每一项都有明确依据：

- **相关性 0.65**：候选摘要与库内文档摘要向量的余弦相似度（BGE-M3）；
- **可复现性 0.20**：元数据里是否出现 GitHub 链接（赛题明确要求"优先推荐附带开源代码"）；
- **时效性 0.15**：发表年份相对最新年份的衰减，避免永远推荐老经典。

推荐理由也由这三项生成，而不是让模型编一句"该论文具有重要意义"。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from ..models.schema import ParsedDocument
from .arxiv_client import ArxivPaper
from .retrieval import get_embedder

W_RELEVANCE = 0.65
W_CODE = 0.20
W_RECENCY = 0.15


@dataclass
class Suggestion:
    paper: ArxivPaper
    score: float
    relevance: float
    reasons: list[str]
    in_library: bool

    def to_dict(self) -> dict:
        return {
            **self.paper.to_dict(),
            "score": round(self.score, 4),
            "relevance": round(self.relevance, 4),
            "reasons": self.reasons,
            "in_library": self.in_library,
        }


_LIB_CACHE: dict[str, np.ndarray] = {}


def _library_signature(docs: list[ParsedDocument]) -> str:
    return "|".join(sorted(f"{d.doc_id}:{len(d.abstract or '')}" for d in docs))


def _library_vector(docs: list[ParsedDocument]) -> np.ndarray | None:
    """库内主题向量（质心）。

    这里必须缓存：BGE-M3 在 CPU 上编码 8 篇 2000 字的摘要要 10 秒以上，
    每次检索都重算会让接口稳定在 20 秒——比 arXiv 本身还慢两个数量级。
    """
    if not docs:
        return None
    signature = _library_signature(docs)
    cached = _LIB_CACHE.get(signature)
    if cached is not None:
        return cached

    texts = [f"{d.title}. {(d.abstract or '')[:800]}" for d in docs if d.title or d.abstract]
    if not texts:
        return None
    vectors = get_embedder().encode(texts)
    centroid = vectors.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm <= 0:
        return None
    centroid = centroid / norm
    _LIB_CACHE.clear()
    _LIB_CACHE[signature] = centroid
    return centroid


def _year(published: str) -> int | None:
    m = re.search(r"(\d{4})", published or "")
    return int(m.group(1)) if m else None


def rank(
    candidates: list[ArxivPaper], docs: list[ParsedDocument], top_k: int = 10
) -> list[Suggestion]:
    if not candidates:
        return []

    centroid = _library_vector(docs)
    encoder = get_embedder()

    years = [y for y in (_year(c.published) for c in candidates) if y]
    newest = max(years) if years else datetime.now().year
    oldest = min(years) if years else newest

    # 只取标题 + 摘要前 600 字：足够判断主题，编码耗时却降到 1/3 以下
    embeddings = encoder.encode([f"{c.title}. {c.summary[:600]}" for c in candidates])
    library_ids = {_arxiv_from_name(d.file_name) for d in docs}
    library_ids.discard("")

    suggestions: list[Suggestion] = []
    for paper, vector in zip(candidates, embeddings):
        relevance = float(np.dot(vector, centroid)) if centroid is not None else 0.0
        relevance = max(0.0, min(1.0, relevance))

        year = _year(paper.published)
        if year and newest > oldest:
            recency = (year - oldest) / (newest - oldest)
        else:
            recency = 1.0

        has_code = bool(paper.code_url)
        score = W_RELEVANCE * relevance + W_CODE * (1.0 if has_code else 0.0) + W_RECENCY * recency

        reasons: list[str] = []
        if relevance > 0:
            reasons.append(f"与库内主题相关度 {relevance:.2f}")
        if has_code:
            reasons.append(f"附带开源实现（{paper.code_url.split('github.com/')[-1]}）")
        else:
            reasons.append("未在元数据中发现代码仓库")
        if year:
            reasons.append(f"{year} 年发表")
        if paper.comment:
            reasons.append(f"作者备注：{paper.comment[:60]}")

        suggestions.append(
            Suggestion(
                paper=paper,
                score=score,
                relevance=relevance,
                reasons=reasons,
                in_library=paper.arxiv_id in library_ids,
            )
        )

    suggestions.sort(key=lambda s: -s.score)
    return suggestions[:top_k]


def _arxiv_from_name(file_name: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})", file_name or "")
    return m.group(1) if m else ""


def dedupe_candidates(candidates: list[ArxivPaper], docs: list[ParsedDocument]) -> list[ArxivPaper]:
    """按标题相似度丢弃已入库的候选，避免推荐里全是自己已有的论文。"""
    known = {_norm(d.title) for d in docs}
    out: list[ArxivPaper] = []
    for paper in candidates:
        key = _norm(paper.title)
        if not key:
            continue
        if any(key[:60] in k or k[:60] in key for k in known if k):
            continue
        out.append(paper)
    return out


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def recency_decay(year: int | None, reference: int | None) -> float:
    """指数衰减，用于展示"这篇论文有多新"。"""
    if not year or not reference:
        return 0.0
    return math.exp(-max(0, reference - year) / 3.0)
