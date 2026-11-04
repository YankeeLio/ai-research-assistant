"""基于正文语义的重复/版本判定。

为什么不能只看文件名或哈希
--------------------------
arXiv 上同一篇论文的 v1 与 v7 文件名只差一个字符，内容却可能改了几十处；
而文件名完全不同的两篇论文也可能是同一工作的预印本与正式版。因此判定必须
回到**正文本身**：

1. **段落级 8-gram shingle 的 Jaccard**：对局部改写不敏感，对"同一篇的不同版本"高度敏感；
2. **SimHash**：64 位指纹，用于快速预筛（汉明距离）；
3. **标题相似度**：作为旁证，避免把"同一主题的两篇不同论文"误判成版本关系。

三者结合给出 `identical / same_work / related / different` 四级结论，
并据此生成"保留哪个版本"的建议。
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from ..models.schema import ParsedDocument

SHINGLE_SIZE = 8
MIN_PARA_CHARS = 80
MAX_SHINGLES = 20000

_TOKEN_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")


@dataclass
class Fingerprint:
    doc_id: str
    title_key: str
    simhash: str  # 16 进制字符串，便于落库比较
    shingles: list[int] = field(default_factory=list)
    para_count: int = 0
    char_count: int = 0
    page_count: int = 0

    def to_json(self) -> dict:
        return asdict(self)

    @classmethod
    def from_json(cls, payload: dict) -> "Fingerprint":
        return cls(**payload)


@dataclass
class Match:
    doc_id: str
    similarity: float
    title_similarity: float
    verdict: str  # identical | same_work | related | different
    reasons: list[str] = field(default_factory=list)


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", title.lower())


def _simhash(text: str, bits: int = 64) -> int:
    weights = [0] * bits
    for token in _tokens(text):
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)
        for i in range(bits):
            weights[i] += 1 if (h >> i) & 1 else -1
    value = 0
    for i, w in enumerate(weights):
        if w > 0:
            value |= 1 << i
    return value


def _shingles(parsed: ParsedDocument) -> list[int]:
    """取正文段落（跳过标题、参考文献、表格），做 8-gram 哈希集合。"""
    hashes: set[int] = set()
    for block in parsed.blocks:
        if block.kind != "paragraph" or len(block.text) < MIN_PARA_CHARS:
            continue
        tokens = _tokens(block.text)
        if len(tokens) < SHINGLE_SIZE:
            continue
        for i in range(len(tokens) - SHINGLE_SIZE + 1):
            gram = " ".join(tokens[i : i + SHINGLE_SIZE])
            hashes.add(int(hashlib.blake2b(gram.encode("utf-8"), digest_size=8).hexdigest(), 16))
            if len(hashes) >= MAX_SHINGLES:
                break
        if len(hashes) >= MAX_SHINGLES:
            break
    return sorted(hashes)


def build_fingerprint(parsed: ParsedDocument) -> Fingerprint:
    body = " ".join(b.text for b in parsed.blocks if b.kind == "paragraph")
    return Fingerprint(
        doc_id=parsed.doc_id,
        title_key=_normalize_title(parsed.title or parsed.file_name),
        simhash=f"{_simhash(body):016x}",
        shingles=_shingles(parsed),
        para_count=sum(1 for b in parsed.blocks if b.kind == "paragraph"),
        char_count=len(body),
        page_count=parsed.stats.page_count if parsed.stats else 0,
    )


def save_fingerprint(fp: Fingerprint, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "fingerprint.json").write_text(
        json.dumps(fp.to_json(), ensure_ascii=False), encoding="utf-8"
    )


def load_fingerprint(directory: Path) -> Fingerprint | None:
    path = directory / "fingerprint.json"
    if not path.exists():
        return None
    try:
        return Fingerprint.from_json(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None


def _jaccard(a: list[int], b: list[int]) -> float:
    if not a or not b:
        return 0.0
    set_a, set_b = set(a), set(b)
    inter = len(set_a & set_b)
    union = len(set_a | set_b)
    return inter / union if union else 0.0


def _hamming_ratio(a: str, b: str) -> float:
    """SimHash 汉明距离转 0-1 相似度（64 位）。"""
    try:
        x = int(a, 16) ^ int(b, 16)
    except ValueError:
        return 0.0
    return 1.0 - bin(x).count("1") / 64.0


def compare(incoming: Fingerprint, existing: Fingerprint) -> Match:
    sim = _jaccard(incoming.shingles, existing.shingles)
    title_sim = SequenceMatcher(None, incoming.title_key, existing.title_key).ratio()
    hamming = _hamming_ratio(incoming.simhash, existing.simhash)
    reasons: list[str] = []

    if title_sim >= 0.95:
        # 标题完全一致时，shingle 与 SimHash 都是强证据，取二者较大值避免过度惩罚改写
        sim = max(sim, hamming * 0.95)
        reasons.append(f"标题一致({title_sim:.2f})")

    if sim >= 0.97:
        verdict = "identical"
        reasons.append(f"正文重合度 {sim:.3f}")
    elif sim >= 0.6:
        verdict = "same_work"
        reasons.append(f"正文重合度 {sim:.3f}（同一工作的不同版本）")
    elif sim >= 0.3:
        verdict = "related"
        reasons.append(f"正文重合度 {sim:.3f}（主题相关）")
    else:
        verdict = "different"
        reasons.append(f"正文重合度 {sim:.3f}")

    return Match(
        doc_id=existing.doc_id,
        similarity=round(sim, 4),
        title_similarity=round(title_sim, 4),
        verdict=verdict,
        reasons=reasons,
    )


def find_best_match(incoming: Fingerprint, pool: list[Fingerprint]) -> Match | None:
    matches = [compare(incoming, other) for other in pool if other.doc_id != incoming.doc_id]
    if not matches:
        return None
    best = max(matches, key=lambda m: m.similarity)
    return best if best.verdict != "different" else None


def _version_number(hint: str) -> int:
    m = re.search(r"(\d+)", hint or "")
    return int(m.group(1)) if m else 0


def recommend(incoming_version: str, existing_version: str, match: Match) -> dict:
    """给出"覆盖 / 保留 / 并存"的建议与理由。"""
    if match.verdict == "identical":
        return {
            "action": "keep_existing",
            "message": "库中已有完全相同的论文，无需重复入库。",
        }

    inc_v, old_v = _version_number(incoming_version), _version_number(existing_version)
    if match.verdict == "same_work":
        if inc_v and old_v and inc_v < old_v:
            return {
                "action": "keep_existing",
                "message": f"库中已有更新版本（{existing_version} > {incoming_version}），建议保留现有版本。",
            }
        if inc_v and old_v and inc_v > old_v:
            return {
                "action": "replace",
                "message": f"本次上传为更新版本（{incoming_version} > {existing_version}），建议替换旧版。",
            }
        return {
            "action": "review",
            "message": "检测到同一工作的不同版本，建议人工确认保留哪一版。",
        }

    return {"action": "keep_both", "message": "与库中文献主题相关但并非同一版本，可并存。"}
