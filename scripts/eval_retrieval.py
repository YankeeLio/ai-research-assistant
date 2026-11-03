"""端到端检索评测：解析 → 分块 → 建索引 → 多策略命中率对比。

用法:
    python scripts/eval_retrieval.py [pdf 路径]

不依赖正在运行的服务，可在离线环境复现；结果用于技术文档的检索章节。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))

import numpy as np  # noqa: E402

from app.services.chunking import chunk_document  # noqa: E402
from app.services.parser import PdfParser  # noqa: E402
from app.services.retrieval import DocumentIndex, get_embedder, tokenize  # noqa: E402

PDF = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("pdf/1706.03762v7.pdf")

# 问题 → 标准答案中的特征串（取自论文原文，用于判定命中）
CASES: list[tuple[str, str]] = [
    ("What GPU models and how many were used to train the models?", "NVIDIA P100"),
    ("What BLEU score did the big model achieve on WMT 2014 English-to-German?", "28.4"),
    ("How many attention heads h and what are the dimensions dk and dv?", "h=8"),
    ("Which optimizer and what beta2 value was used?", "0.98"),
    ("How many layers are in the encoder and decoder?", "N=6"),
]

VARIANTS = {
    "bm25_only": (1.0, 0.0),
    "dense_only": (0.0, 1.0),
    "rrf_balanced": (1.0, 1.0),
    "rrf_dense_primary": (0.3, 1.0),
    "rrf_sparse_primary": (1.0, 0.3),
}


def _norm(text: str) -> str:
    """比对前去掉所有空白：PDF 抽取的空格位置不可靠，命中断言不该受它影响。"""
    return "".join(text.split())


def rrf(values: np.ndarray, k: int = 60) -> np.ndarray:
    ranks = np.argsort(np.argsort(-values)) + 1
    return 1.0 / (k + ranks)


def main() -> None:
    t0 = time.perf_counter()
    parsed = PdfParser().parse(PDF, "eval")
    chunks = chunk_document(parsed)
    embedder = get_embedder()
    index = DocumentIndex.build("eval", chunks, embedder)
    print(f"解析 {parsed.stats.page_count} 页, {len(chunks)} 块, 建索引 {time.perf_counter() - t0:.1f}s")
    print(f"embedder={embedder.name}\n")

    precomputed = []
    for question, _needle in CASES:
        sparse = index.bm25.scores(tokenize(question))
        dense = index.vectors @ embedder.encode([question])[0]
        precomputed.append((sparse, dense))

    header = f"{'策略':<16}" + "".join(f"Q{i + 1:<3}" for i in range(len(CASES))) + " 命中@3"
    print(header)
    print("-" * len(header))
    best = ("", -1)
    for name, (w_sparse, w_dense) in VARIANTS.items():
        marks, hits = [], 0
        for (sparse, dense), (_q, needle) in zip(precomputed, CASES):
            fused = w_sparse * rrf(sparse) + w_dense * rrf(dense)
            top = [_norm(index.chunks[i].text) for i in np.argsort(-fused)[:3]]
            ok = any(_norm(needle) in text for text in top)
            hits += int(ok)
            marks.append("✓" if ok else "✗")
        print(f"{name:<16}" + "".join(f"{m:<4}" for m in marks) + f" {hits}/{len(CASES)}")
        if hits > best[1]:
            best = (name, hits)

    print(f"\n最优: {best[0]}  {best[1]}/{len(CASES)}")


if __name__ == "__main__":
    main()
