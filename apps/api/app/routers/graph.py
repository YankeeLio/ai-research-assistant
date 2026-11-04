"""局域引用图谱接口。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..core import db
from ..models.schema import ParsedDocument
from ..services import graph as graph_service
from ..services import survey

router = APIRouter(tags=["graph"])


def _load_all() -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for row in db.list_documents():
        if row["status"] != "ready":
            continue
        payload = db.load_parsed(row["doc_id"])
        if payload:
            docs.append(ParsedDocument.model_validate(payload))
    return docs


@router.get("/graph")
def get_graph() -> dict:
    docs = _load_all()
    if not docs:
        raise HTTPException(status_code=404, detail="文献库为空")
    return graph_service.to_payload(graph_service.build_graph(docs))


@router.get("/graph/survey")
def get_survey() -> dict:
    docs = _load_all()
    if not docs:
        raise HTTPException(status_code=404, detail="文献库为空")
    built = graph_service.build_graph(docs)
    return survey.generate(built, docs)
