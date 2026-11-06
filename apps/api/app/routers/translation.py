"""中英对照翻译接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..core import db
from ..models.schema import ParsedDocument
from ..services import translate

router = APIRouter(tags=["translation"])


class SelectionRequest(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


@router.post("/translate/selection")
def translate_selection(req: SelectionRequest) -> dict:
    """划词翻译：阅读器里选中一段英文后即时返回中文。"""
    return translate.translate_selection(req.text)


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
