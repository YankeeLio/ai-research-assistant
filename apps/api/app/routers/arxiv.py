"""arXiv 检索、下钻入库与个性化推荐。"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from ..core import db
from ..core.config import get_settings
from ..models.schema import ParsedDocument
from ..services import arxiv_client, ingest, recommend

router = APIRouter(tags=["arxiv"])


def _library_docs() -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for row in db.list_documents():
        if row["status"] != "ready":
            continue
        payload = db.load_parsed(row["doc_id"])
        if payload:
            docs.append(ParsedDocument.model_validate(payload))
    return docs


@router.get("/arxiv/search")
def search(
    q: str = Query(..., min_length=2, description="检索词，支持 arXiv 语法"),
    max_results: int = Query(default=15, ge=1, le=40),
    sort: str = Query(default="relevance", pattern="^(relevance|date)$"),
    with_ranking: bool = Query(default=True, description="是否按本地文献库相关性重排"),
) -> dict:
    try:
        papers = arxiv_client.search(q, max_results=max_results, sort=sort)
    except Exception as exc:  # noqa: BLE001 - 上游网络问题要给出可读错误
        raise HTTPException(status_code=502, detail=f"arXiv 检索失败: {exc}") from exc

    if not with_ranking:
        return {"query": q, "count": len(papers), "items": [p.to_dict() for p in papers]}

    docs = _library_docs()
    fresh = recommend.dedupe_candidates(papers, docs)
    ranked = recommend.rank(fresh, docs)
    return {
        "query": q,
        "count": len(ranked),
        "filtered_in_library": len(papers) - len(fresh),
        "items": [s.to_dict() for s in ranked],
    }


class IngestRequest(BaseModel):
    arxiv_id: str = Field(min_length=4, description="arXiv ID，如 1810.04805")


@router.post("/arxiv/ingest")
def ingest_paper(req: IngestRequest, background: BackgroundTasks) -> dict:
    paper = arxiv_client.fetch_by_id(req.arxiv_id)
    if paper is None:
        raise HTTPException(status_code=404, detail=f"arXiv 上找不到 {req.arxiv_id}")

    doc_id = uuid.uuid4().hex[:12]
    target_dir = get_settings().docs_dir / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / "original.pdf"
    try:
        downloaded = arxiv_client.download_pdf(paper.arxiv_id, target_dir / "_src")
        pdf_path.write_bytes(downloaded.read_bytes())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"PDF 下载失败: {exc}") from exc

    summary = ingest.store_document(doc_id, pdf_path, f"{paper.arxiv_id}.pdf")
    background.add_task(_warm, doc_id)
    return {"paper": paper.to_dict(), "document": summary.model_dump()}


def _warm(doc_id: str) -> None:
    from ..services import qa

    try:
        qa.ensure_index(doc_id)
    except Exception:  # noqa: BLE001
        pass


@router.post("/arxiv/download-by-title")
def download_by_title(title: str = Query(..., min_length=4), background: BackgroundTasks = None) -> dict:
    """给定论文名称自动下钻：先查 arXiv，再走统一入库管道。"""
    paper = arxiv_client.search_by_title(title)
    if paper is None:
        raise HTTPException(status_code=404, detail="按标题未在 arXiv 找到匹配")
    return ingest_paper(IngestRequest(arxiv_id=paper.arxiv_id), background or BackgroundTasks())


@router.get("/recommend")
def recommend_for_library(
    q: str = Query(default="large language model", description="检索主题，默认取泛化主题"),
    max_results: int = Query(default=20, ge=5, le=40),
    top_k: int = Query(default=8, ge=1, le=20),
) -> dict:
    docs = _library_docs()
    if not docs:
        raise HTTPException(status_code=404, detail="文献库为空，无法做个性化推荐")
    try:
        papers = arxiv_client.search(q, max_results=max_results, sort="date")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"arXiv 检索失败: {exc}") from exc
    fresh = recommend.dedupe_candidates(papers, docs)
    ranked = recommend.rank(fresh, docs, top_k=top_k * 2)
    # 只保留与库内主题确有关系的候选：低于 0.55 的通常是同域噪声
    ranked = [s for s in ranked if s.relevance >= 0.55][:top_k]
    return {"query": q, "library_size": len(docs), "items": [s.to_dict() for s in ranked]}
