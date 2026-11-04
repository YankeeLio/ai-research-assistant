"""arXiv 检索与下载：只用标准库解析 Atom，避免引入额外 SDK。

设计取舍
--------
- **只读开放接口**：`export.arxiv.org/api/query` 无需 Key，但要遵守 3 秒请求间隔，
  否则会被限流（实测连续快速请求会返回 429）。
- **PDF 与元数据分离**：元数据用于推荐和筛选，PDF 只在用户确认入库时才下载，
  避免把磁盘塞满。
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

API = "https://export.arxiv.org/api/query"
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
}
_LAST_CALL = 0.0
_MIN_INTERVAL = 3.0

# 查询结果缓存：推荐与检索常常请求同一主题，重复打 arXiv 既慢又容易被限流
_CACHE: dict[tuple, tuple[float, list["ArxivPaper"]]] = {}
_CACHE_TTL = 600.0

GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/[\w.-]+/[\w.-]+", re.I)


@dataclass
class ArxivPaper:
    arxiv_id: str
    title: str
    summary: str
    authors: list[str] = field(default_factory=list)
    published: str = ""
    updated: str = ""
    categories: list[str] = field(default_factory=list)
    comment: str = ""
    code_url: str = ""
    pdf_url: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _throttle() -> None:
    global _LAST_CALL
    gap = time.time() - _LAST_CALL
    if gap < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - gap)
    _LAST_CALL = time.time()


def _get(params: dict, attempts: int = 3) -> httpx.Response:
    """带退避的 GET：arXiv 对突发请求会返回 429/503，直接抛错会让前端看到 502。"""
    last_exc: Exception | None = None
    for i in range(attempts):
        _throttle()
        try:
            resp = httpx.get(API, params=params, timeout=40, follow_redirects=True)
            if resp.status_code in (429, 500, 502, 503):
                raise httpx.HTTPStatusError(
                    f"arXiv 返回 {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001 - 统一收集后重试
            last_exc = exc
            logger.warning("arXiv 请求失败（第 %d/%d 次）: %s", i + 1, attempts, exc)
            time.sleep(3 * (i + 1))
    assert last_exc is not None
    raise last_exc


def search(query: str, max_results: int = 20, sort: str = "relevance") -> list[ArxivPaper]:
    """按关键词检索 arXiv。query 支持 arXiv 语法，如 `all:"vision transformer"`。"""
    if not query.strip():
        return []
    cache_key = (query, max_results, sort)
    cached = _CACHE.get(cache_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max(1, min(max_results, 50)),
        "sortBy": "relevance" if sort == "relevance" else "submittedDate",
        "sortOrder": "descending",
    }
    resp = _get(params)

    root = ET.fromstring(resp.text)
    papers: list[ArxivPaper] = []
    for entry in root.findall("atom:entry", NS):
        raw_id = _text(entry, "atom:id")
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1] if "/abs/" in raw_id else raw_id.rsplit("/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        comment = _text(entry, "arxiv:comment")
        summary = _text(entry, "atom:summary")
        code_url = ""
        for candidate in (comment, summary):
            m = GITHUB_RE.search(candidate or "")
            if m:
                code_url = m.group(0)
                break
        papers.append(
            ArxivPaper(
                arxiv_id=arxiv_id,
                title=" ".join(_text(entry, "atom:title").split()),
                summary=" ".join(summary.split()),
                authors=[
                    _text(a, "atom:name") for a in entry.findall("atom:author", NS)
                ],
                published=_text(entry, "atom:published"),
                updated=_text(entry, "atom:updated"),
                categories=[
                    c.get("term", "") for c in entry.findall("atom:category", NS)
                ],
                comment=" ".join((comment or "").split()),
                code_url=code_url,
                pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
            )
        )
    _CACHE[cache_key] = (time.time(), papers)
    return papers


def fetch_by_id(arxiv_id: str) -> ArxivPaper | None:
    """按 ID 精确取一篇（用于"给定论文名/链接自动下载入库"）。"""
    arxiv_id = arxiv_id.strip()
    arxiv_id = re.sub(r"^.*/abs/", "", arxiv_id)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
    try:
        resp = _get({"id_list": arxiv_id})
    except Exception as exc:  # noqa: BLE001
        logger.warning("arXiv 取元数据失败: %s", exc)
        return None
    root = ET.fromstring(resp.text)
    entries = root.findall("atom:entry", NS)
    if not entries:
        return None
    entry = entries[0]
    comment = _text(entry, "arxiv:comment")
    summary = _text(entry, "atom:summary")
    code = ""
    for candidate in (comment, summary):
        m = GITHUB_RE.search(candidate or "")
        if m:
            code = m.group(0)
            break
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=" ".join(_text(entry, "atom:title").split()),
        summary=" ".join(summary.split()),
        authors=[_text(a, "atom:name") for a in entry.findall("atom:author", NS)],
        published=_text(entry, "atom:published"),
        updated=_text(entry, "atom:updated"),
        categories=[c.get("term", "") for c in entry.findall("atom:category", NS)],
        comment=" ".join((comment or "").split()),
        code_url=code,
        pdf_url=f"https://arxiv.org/pdf/{arxiv_id}",
    )


def download_pdf(arxiv_id: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f"{arxiv_id.replace('/', '_')}.pdf"
    if target.exists() and target.stat().st_size > 50_000:
        return target
    _throttle()
    with httpx.stream(
        "GET",
        f"https://arxiv.org/pdf/{arxiv_id}",
        headers={"User-Agent": "SciLoom/0.1 (research assistant)"},
        follow_redirects=True,
        timeout=180,
    ) as resp:
        resp.raise_for_status()
        with target.open("wb") as fh:
            for chunk in resp.iter_bytes(1 << 16):
                fh.write(chunk)
    return target


def search_by_title(title: str) -> ArxivPaper | None:
    """按论文标题模糊查找（取第一条），用于"给定论文名称自动下钻"。"""
    if not title.strip():
        return None
    quoted = quote(f'all:"{title}"')
    results = search(f"all:{quoted}", max_results=5)
    if not results:
        results = search(f"all:{quote(title)}", max_results=5)
    return results[0] if results else None


def _text(node: ET.Element | None, tag: str) -> str:
    if node is None:
        return ""
    child = node.find(tag, NS)
    return (child.text or "").strip() if child is not None else ""
