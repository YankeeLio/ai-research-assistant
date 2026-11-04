"""批量下载 Transformer 谱系的经典论文并入库，用于构建局域引用图谱。

用法:
    python scripts/fetch_related.py            # 下载并入库
    python scripts/fetch_related.py --skip-existing

论文选择标准：与 1706.03762 有真实引用关系、覆盖"注意力机制 → Transformer → BERT/GPT/T5"
这条主线，这样图谱才有结构可讲，而不是随机堆论文。
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import httpx

PAPERS = [
    ("1409.0473", "Neural Machine Translation by Jointly Learning to Align and Translate"),
    ("1607.06450", "Layer Normalization"),
    ("1412.6980", "Adam: A Method for Stochastic Optimization"),
    ("1810.04805", "BERT: Pre-training of Deep Bidirectional Transformers"),
    ("1907.11692", "RoBERTa: A Robustly Optimized BERT Pretraining Approach"),
    ("1910.10683", "Exploring the Limits of Transfer Learning with T5"),
    ("2005.14165", "Language Models are Few-Shot Learners (GPT-3)"),
]

PDF_DIR = Path(__file__).resolve().parents[1] / "pdf" / "related"
API = "http://127.0.0.1:8000"
UA = {"User-Agent": "Mozilla/5.0 (SciLoom data fetcher)"}


def download(arxiv_id: str) -> Path:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / f"{arxiv_id}.pdf"
    if target.exists() and target.stat().st_size > 50_000:
        print(f"  已存在 {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        return target
    print(f"  下载 {arxiv_id} …")
    with httpx.stream(
        "GET", f"https://arxiv.org/pdf/{arxiv_id}", headers=UA, follow_redirects=True, timeout=300
    ) as r:
        r.raise_for_status()
        with target.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 16):
                fh.write(chunk)
    print(f"  -> {target.stat().st_size / 1024 / 1024:.1f} MB")
    return target


def main() -> None:
    skip_existing = "--skip-existing" in sys.argv

    with httpx.Client(base_url=API, timeout=900) as client:
        existing = {d["file_name"] for d in client.get("/api/documents").json()}
        for arxiv_id, title in PAPERS:
            name = f"{arxiv_id}.pdf"
            if skip_existing and name in existing:
                print(f"跳过 {name}（已入库）")
                continue
            path = download(arxiv_id)
            print(f"  解析入库：{title[:50]} …")
            started = time.perf_counter()
            with path.open("rb") as fh:
                resp = client.post(
                    "/api/documents/upload", files={"file": (name, fh, "application/pdf")}
                )
            if resp.status_code != 200:
                print(f"  失败: {resp.status_code} {resp.text[:160]}")
                continue
            doc = resp.json()
            flag = ""
            if doc.get("duplicate_of"):
                flag = f"  [重复: {doc['duplicate_verdict']}]"
            print(
                f"  ok {doc['page_count']}p, {doc['stats']['reference_count'] if doc.get('stats') else '?'} refs"
                f", {time.perf_counter() - started:.1f}s{flag}"
            )


if __name__ == "__main__":
    main()
