"""中英对照翻译接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..core import db
from ..models.schema import ParsedDocument
from ..services import translate

router = APIRouter(tags=["translation"])


@router.post("/documents/{doc_id}/translate")
def run_translation(doc_id: str, force: bool = Query(default=False)) -> dict:
    payload = db.load_parsed(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="文档不存在或尚未解析")
    parsed = ParsedDocument.model_validate(payload)
    result = translate.translate_document(doc_id, parsed, force=force)
    return {
        "doc_id": doc_id,
        "translator": result.get("translator"),
        "count": result.get("count", 0),
    }


@router.get("/documents/{doc_id}/translation")
def get_translation(doc_id: str) -> dict:
    payload = translate.load_translation(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="尚未生成译文")
    return payload
