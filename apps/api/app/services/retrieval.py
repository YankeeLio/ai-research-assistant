"""混合检索：BM25（稀疏）+ 向量（稠密）+ 可选 rerank。

为什么不是纯向量
----------------
学术问题的很多关键词是**精确串**：`β2`、`BLEU 28.4`、`8 NVIDIA P100`、`[11]`。
向量模型对这类串不敏感，反而 BM25 一击即中；而"这一段在讲什么"这类语义问题
只有向量能答。因此两路召回后做分数归一化融合，再由 rerank 精排。
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

import numpy as np

from ..core.config import get_settings
from .chunking import Chunk

logger = logging.getLogger(__name__)

TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:[.\-_/][A-Za-z0-9]+)*|[\u4e00-\u9fff]+")


def tokenize(text: str) -> list[str]:
    """英文按词、中文按字 + 二元组切分，兼顾精确串与中文语义。"""
    tokens: list[str] = []
    for match in TOKEN_RE.findall(text):
        if "\u4e00" <= match[0] <= "\u9fff":
            tokens.extend(match)
            tokens.extend(match[i : i + 2] for i in range(len(match) - 1))
        else:
            tokens.append(match.lower())
    return tokens


class BM25:
    """Okapi BM25，纯 numpy 实现以避免额外的检索依赖。"""

    def __init__(self, corpus_tokens: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.doc_len = np.array([len(t) for t in corpus_tokens], dtype=np.float32)
        self.avg_len = float(self.doc_len.mean()) if len(corpus_tokens) else 0.0
        self.term_freqs = [Counter(t) for t in corpus_tokens]
        df = Counter({term for tf in self.term_freqs for term in tf})
        n = max(1, len(corpus_tokens))
        self.idf = {term: math.log(1 + (n - freq + 0.5) / (freq + 0.5)) for term, freq in df.items()}

    def scores(self, query_tokens: list[str]) -> np.ndarray:
        out = np.zeros(len(self.term_freqs), dtype=np.float32)
        for term in query_tokens:
            idf = self.idf.get(term)
            if idf is None:
                continue
            for i, tf in enumerate(self.term_freqs):
                freq = tf.get(term, 0)
                if not freq:
                    continue
                norm = 1 - self.b + self.b * (self.doc_len[i] / (self.avg_len or 1.0))
                out[i] += idf * (freq * (self.k1 + 1)) / (freq + self.k1 * norm)
        return out


class Embedder(Protocol):
    dim: int
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class HashingEmbedder:
    """零依赖兜底：词袋哈希到固定维度。

    仅用于未配置模型的环境下跑通链路与做回归测试，**不具备语义泛化能力**，
    生产/演示必须切换到 BGE-M3。
    """

    name = "hashing-fallback"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                idx = hash(token) % self.dim
                out[row, idx] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-8)


class SentenceTransformerEmbedder:
    name = "bge-m3"

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer  # 懒加载，避免影响启动

        self.model = SentenceTransformer(model_name)
        self.dim = int(self.model.get_sentence_embedding_dimension() or 1024)

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


def get_embedder() -> Embedder:
    settings = get_settings()
    if settings.embedding_backend == "local":
        try:
            return SentenceTransformerEmbedder(settings.embedding_model)
        except Exception as exc:  # noqa: BLE001 - 模型缺失时降级而不是崩溃
            logger.warning("本地向量模型不可用（%s），降级为哈希向量", exc)
    return HashingEmbedder()


class DocumentIndex:
    """单篇文档的检索索引，落盘为 vectors.npz + chunks.json。"""

    def __init__(self, doc_id: str, chunks: list[Chunk], vectors: np.ndarray) -> None:
        self.doc_id = doc_id
        self.chunks = chunks
        self.vectors = vectors
        self.bm25 = BM25([tokenize(c.text) for c in chunks])

    # ------------------------------------------------------------------ build
    @classmethod
    def build(cls, doc_id: str, chunks: list[Chunk], embedder: Embedder) -> "DocumentIndex":
        vectors = embedder.encode([c.text for c in chunks]) if chunks else np.zeros((0, 1), np.float32)
        return cls(doc_id, chunks, vectors)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(directory / "vectors.npz", vectors=self.vectors)
        (directory / "chunks.json").write_text(
            json.dumps(
                [
                    {
                        "id": c.id,
                        "doc_id": c.doc_id,
                        "text": c.text,
                        "page": c.page,
                        "block_ids": c.block_ids,
                        "section_path": c.section_path,
                        "kind": c.kind,
                    }
                    for c in self.chunks
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, doc_id: str, directory: Path) -> "DocumentIndex | None":
        meta_path = directory / "chunks.json"
        vec_path = directory / "vectors.npz"
        if not meta_path.exists() or not vec_path.exists():
            return None
        rows = json.loads(meta_path.read_text(encoding="utf-8"))
        chunks = [Chunk(**row) for row in rows]
        vectors = np.load(vec_path)["vectors"]
        return cls(doc_id, chunks, vectors)

    # ----------------------------------------------------------------- search
    def search(self, query: str, top_k: int = 8) -> list[tuple[Chunk, float]]:
        if not self.chunks:
            return []
        sparse = self.bm25.scores(tokenize(query))
        sparse_norm = _minmax(sparse)

        embedder = get_embedder()
        qvec = embedder.encode([query])[0]
        dense = self.vectors @ qvec
        dense_norm = _minmax(dense)

        fused = 0.55 * sparse_norm + 0.45 * dense_norm
        order = np.argsort(-fused)[: max(top_k * 3, top_k)]
        picked = [(self.chunks[i], float(fused[i])) for i in order]
        return picked[:top_k]


def _minmax(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values
    lo, hi = float(values.min()), float(values.max())
    if hi - lo < 1e-9:
        return np.zeros_like(values)
    return (values - lo) / (hi - lo)
