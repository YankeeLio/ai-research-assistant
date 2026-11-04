"""问答与检索接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services import qa

router = APIRouter(tags=["qa"])


class AskRequest(BaseModel):
    doc_id: str
    question: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=8, ge=1, le=20)


@router.post("/qa/ask")
async def ask(req: AskRequest) -> dict:
    index = qa.ensure_index(req.doc_id)
    if index is None:
        raise HTTPException(status_code=404, detail="文档不存在或尚未解析")
    return await qa.answer(req.doc_id, req.question, top_k=req.top_k)


@router.get("/qa/stream")
async def stream(
    doc_id: str = Query(...), q: str = Query(..., min_length=1, max_length=500), top_k: int = 8
):
    async def generate():
        # 首次提问时索引可能还没建好：先推一条状态帧，避免前端对着空白等一分钟
        if qa.load_index(doc_id) is None:
            yield qa.sse({"type": "status", "message": "正在建立检索索引…"})
            index = await run_in_threadpool(qa.ensure_index, doc_id)
            if index is None:
                yield qa.sse({"type": "error", "message": "文档不存在或尚未解析"})
                return
            yield qa.sse({"type": "status", "message": "索引就绪，开始检索…"})
        async for chunk in qa.stream_answer(doc_id, q, top_k=top_k):
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/documents/{doc_id}/search")
def search(doc_id: str, q: str = Query(..., min_length=1), top_k: int = 8) -> dict:
    index = qa.ensure_index(doc_id)
    if index is None:
        raise HTTPException(status_code=404, detail="文档不存在或尚未解析")
    hits = index.search(q, top_k=top_k)
    return {
        "query": q,
        "hits": [
            {
                "chunk_id": c.id,
                "page": c.page,
                "section": c.section_path,
                "score": round(score, 4),
                "text": c.text,
            }
            for c, score in hits
        ],
    }


@router.post("/documents/{doc_id}/index")
def rebuild_index(doc_id: str) -> dict:
    index = qa.ensure_index(doc_id)
    if index is None:
        raise HTTPException(status_code=404, detail="文档不存在或尚未解析")
    return {"doc_id": doc_id, "chunks": len(index.chunks), "vectors": int(index.vectors.shape[0])}
