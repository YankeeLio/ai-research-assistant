"""端到端检索评测：解析 → 分块 → 建索引 → 多策略命中率对比。

用法:
    python scripts/eval_retrieval.py [pdf 路径]

不依赖正在运行的服务，可在离线环境复现；结果用于技术文档的检索章节。
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

import numpy as np  # noqa: E402

from app.services.chunking import chunk_document  # noqa: E402
from app.services.parser import PdfParser  # noqa: E402
from app.services.retrieval import (  # noqa: E402
    DocumentIndex,
    _rrf,
    get_embedder,
    tokenize,
)

PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pdf/1706.03762v7.pdf")

# 问题 → 标准答案中的特征串（取自论文原文）。首条为中文提问，用于检验跨语言检索。
CASES: list[tuple[str, str]] = [
    ("用了多少块 GPU，什么型号？", "8 NVIDIA P100"),
    ("What GPU models and how many were used to train the models?", "NVIDIA P100"),
    ("What BLEU score did the big model achieve on WMT 2014 English-to-German?", "28.4"),
    ("How many attention heads h and what are the dimensions dk and dv?", "h=8"),
    ("Which optimizer and what beta2 value was used?", "0.98"),
    ("How many layers are in the encoder and decoder?", "N=6"),
]


def _norm(text: str) -> str:
    """比对前去掉所有空白：PDF 抽取的空格位置不可靠，命中断言不该受它影响。"""
    return "".join(text.split())


def main() -> None:
    t0 = time.perf_counter()
    parsed = PdfParser().parse(PDF, "eval")
    chunks = chunk_document(parsed)
    embedder = get_embedder()
    index = DocumentIndex.build("eval", chunks, embedder)
    print(f"解析 {parsed.stats.page_count} 页, {len(chunks)} 块, 建索引 {time.perf_counter() - t0:.1f}s")
    print(f"embedder={embedder.name}\n")

    queries = [q for q, _ in CASES]
    sparse_all = [index.bm25.scores(tokenize(q)) for q in queries]
    dense_all = [index.vectors @ embedder.encode([q])[0] for q in queries]

    def dense_only(i: int) -> np.ndarray:
        return _rrf(dense_all[i])

    def bm25_only(i: int) -> np.ndarray:
        return _rrf(sparse_all[i])

    def fixed_half(i: int) -> np.ndarray:
        return _rrf(dense_all[i]) + _rrf(sparse_all[i])

    def current(i: int) -> np.ndarray:
        """线上策略：稠密召回 + 短名单内稀疏重排（见 DocumentIndex.search）。"""
        q = queries[i]
        sparse = sparse_all[i]
        dense = dense_all[i]
        shortlist = np.argsort(-dense)[:50]
        weight = index._sparse_weight(tokenize(q))  # noqa: SLF001 - 评测即测量该策略
        fused = _rrf(dense[shortlist]) + weight * _rrf(sparse[shortlist])
        out = np.full_like(dense, -1.0)
        out[shortlist] = fused
        return out

    variants: dict[str, Callable[[int], np.ndarray]] = {
        "bm25_only": bm25_only,
        "dense_only": dense_only,
        "rrf_balanced": fixed_half,
        "current(adaptive)": current,
    }

    header = f"{'策略':<18}" + "".join(f"Q{i + 1:<3}" for i in range(len(CASES))) + " @3    top1"
    print(header)
    print("-" * len(header))

    for name, scorer in variants.items():
        marks, hits, top1 = [], 0, 0
        for i, (_q, needle) in enumerate(CASES):
            order = np.argsort(-scorer(i))[:3]
            texts = [_norm(index.chunks[j].text) for j in order]
            ok = any(_norm(needle) in t for t in texts)
            hits += int(ok)
            top1 += int(_norm(needle) in texts[0])
            marks.append("✓" if ok else "✗")
        print(f"{name:<18}" + "".join(f"{m:<4}" for m in marks) + f" {hits}/{len(CASES)}   {top1}/{len(CASES)}")


if __name__ == "__main__":
    main()
