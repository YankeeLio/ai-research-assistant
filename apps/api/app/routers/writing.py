"""写作辅助、图表生成与架构图脚本接口。"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..core import db
from ..models.schema import ParsedDocument
from ..services import viz, writing

router = APIRouter(tags=["writing"])


def _library_docs() -> list[ParsedDocument]:
    docs: list[ParsedDocument] = []
    for row in db.list_documents():
        if row["status"] != "ready":
            continue
        payload = db.load_parsed(row["doc_id"])
        if payload:
            docs.append(ParsedDocument.model_validate(payload))
    return docs


class OutlineRequest(BaseModel):
    idea: str = Field(min_length=4, max_length=500)
    top_k: int = Field(default=5, ge=1, le=10)


@router.post("/writing/outline")
def outline(req: OutlineRequest) -> dict:
    docs = _library_docs()
    if not docs:
        raise HTTPException(status_code=404, detail="文献库为空，无法生成带真实文献的框架")
    return writing.build_outline(req.idea, docs, top_k=req.top_k)


class DiagramRequest(BaseModel):
    stages: list[str] = Field(default_factory=list, max_length=12)
    title: str = "Architecture"


@router.post("/writing/diagram")
def diagram(req: DiagramRequest) -> dict:
    return writing.build_diagram(req.stages, req.title)


@router.post("/viz/chart")
async def chart(
    file: UploadFile = File(...),
    title: str = Query(default="", max_length=200),
    chart_type: str | None = Query(default=None),
) -> dict:
    if not (file.filename or "").lower().endswith((".csv", ".tsv", ".txt")):
        raise HTTPException(status_code=400, detail="请上传 CSV / TSV 文件")
    raw = await file.read()
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 8 MB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    try:
        return viz.render_chart(text, title=title, chart_type=chart_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/figures/{figure_id}.png")
def figure(figure_id: str) -> FileResponse:
    path = viz.figure_path(figure_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="图表不存在")
    return FileResponse(path, media_type="image/png")
