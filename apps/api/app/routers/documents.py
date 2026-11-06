"""文献管理：上传、列表、详情、解析结果、重复检测、版本差异、删除。"""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from ..core import db
from ..core.config import get_settings
from ..core.paths import doc_dir as safe_doc_dir
from ..models.schema import DocumentSummary, ParsedDocument
from ..services import dedupe, version_diff
from ..services.ingest import store_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


def _doc_dir(doc_id: str) -> Path:
    return safe_doc_dir(doc_id)


def _version_hint(file_name: str) -> str:
    m = re.search(r"v(\d+)", file_name, re.I)
    return f"v{m.group(1)}" if m else ""


def _row_to_summary(r: dict) -> DocumentSummary:
    return DocumentSummary(
        doc_id=r["doc_id"],
        file_name=r["file_name"],
        title=r["title"] or r["file_name"],
        authors=json.loads(r["authors"] or "[]"),
        page_count=r["page_count"],
        is_scanned=bool(r["is_scanned"]),
        layout=r["layout"],
        uploaded_at=r["uploaded_at"],
        status=r["status"],
        error=r["error"],
        content_fingerprint=r["fingerprint"],
        version_hint=r["version_hint"],
        duplicate_of=r["duplicate_of"],
        duplicate_similarity=r.get("dup_similarity") or 0.0,
        duplicate_verdict=r.get("dup_verdict") or "",
        duplicate_action=r.get("dup_action") or "",
        duplicate_message=r.get("dup_message") or "",
    )


def _pool(exclude: str | None = None) -> list[dedupe.Fingerprint]:
    """加载库内全部指纹；老文档没有指纹文件时按需补算。"""
    out: list[dedupe.Fingerprint] = []
    for row in db.list_documents():
        doc_id = row["doc_id"]
        if doc_id == exclude:
            continue
        fp = dedupe.load_fingerprint(_doc_dir(doc_id))
        if fp is None:
            payload = db.load_parsed(doc_id)
            if payload is None:
                continue
            parsed = ParsedDocument.model_validate(payload)
            fp = dedupe.build_fingerprint(parsed)
            dedupe.save_fingerprint(fp, _doc_dir(doc_id))
        out.append(fp)
    return out


def _parse_and_store(doc_id: str, pdf_path: Path, file_name: str) -> DocumentSummary:
    """入库管道在 services/ingest.py：上传与 arXiv 自动下钻共用同一套逻辑。"""
    return store_document(doc_id, pdf_path, file_name)


@router.post("/upload", response_model=DocumentSummary)
async def upload_document(
    background: BackgroundTasks, file: UploadFile = File(...)
) -> DocumentSummary:
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    settings = get_settings()
    raw = await file.read()
    if len(raw) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"文件超过 {settings.max_upload_mb} MB")

    doc_id = uuid.uuid4().hex[:12]
    target_dir = settings.docs_dir / doc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = target_dir / "original.pdf"
    pdf_path.write_bytes(raw)

    summary = await run_in_threadpool(
        _parse_and_store, doc_id, pdf_path, file.filename or "untitled.pdf"
    )
    # 向量索引在后台建：解析已经够慢，不该让上传接口再多等一分钟
    background.add_task(_warm_index, doc_id)
    return summary


def _warm_index(doc_id: str) -> None:
    from ..services import qa

    try:
        qa.ensure_index(doc_id)
    except Exception as exc:  # noqa: BLE001 - 预热失败不应影响已入库文档
        logger.warning("索引预热失败 %s: %s", doc_id, exc)


@router.get("", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    return [_row_to_summary(r) for r in db.list_documents()]


@router.get("/{doc_id}", response_model=DocumentSummary)
def get_document(doc_id: str) -> DocumentSummary:
    row = db.get_document(doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")
    return _row_to_summary(row)


@router.get("/{doc_id}/parsed", response_model=ParsedDocument)
def get_parsed(doc_id: str) -> ParsedDocument:
    payload = db.load_parsed(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return ParsedDocument.model_validate(payload)


@router.get("/{doc_id}/file")
def get_file(doc_id: str) -> FileResponse:
    """原始 PDF 字节流，供前端 PDF.js 渲染。"""
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    path = _doc_dir(doc_id) / "original.pdf"
    if not path.exists():
        raise HTTPException(status_code=404, detail="原始文件缺失")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{doc_id}.pdf"'},
    )


@router.get("/{doc_id}/duplicates")
def find_duplicates(doc_id: str) -> dict:
    fp = dedupe.load_fingerprint(_doc_dir(doc_id))
    if fp is None:
        raise HTTPException(status_code=404, detail="指纹不存在（文档可能尚未解析完成）")
    matches = [dedupe.compare(fp, other) for other in _pool(exclude=doc_id)]
    matches = [m for m in matches if m.verdict != "different"]
    matches.sort(key=lambda m: -m.similarity)
    return {
        "doc_id": doc_id,
        "count": len(matches),
        "matches": [
            {"doc_id": m.doc_id, "similarity": m.similarity, "verdict": m.verdict, "reasons": m.reasons}
            for m in matches
        ],
    }


@router.get("/{doc_id}/diff/{other_id}")
def compare_versions(doc_id: str, other_id: str) -> dict:
    """对比两篇文档：`doc_id` 视为旧版，`other_id` 视为新版。"""
    old_payload, new_payload = db.load_parsed(doc_id), db.load_parsed(other_id)
    if old_payload is None or new_payload is None:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    old = ParsedDocument.model_validate(old_payload)
    new = ParsedDocument.model_validate(new_payload)
    diff = version_diff.diff_parsed(old, new)
    return {
        "old": {"doc_id": diff.old_id, "label": diff.old_label},
        "new": {"doc_id": diff.new_id, "label": diff.new_label},
        "similarity": diff.similarity,
        "summary": diff.summary,
        "stats": diff.stats,
        "sections": [
            {
                "title": s.title,
                "status": s.status,
                "similarity": s.similarity,
                "added_sentences": s.added_sentences,
                "removed_sentences": s.removed_sentences,
            }
            for s in diff.sections
        ],
    }


@router.post("/{doc_id}/resolve")
def resolve_duplicate(
    doc_id: str, action: str = Query(..., pattern="^(keep_both|replace|keep_existing)$")
) -> dict:
    """处理重复：replace 表示保留本次上传、删除被判定为旧版的文档。"""
    row = db.get_document(doc_id)
    if not row:
        raise HTTPException(status_code=404, detail="文档不存在")

    other = row["duplicate_of"]
    if action == "replace" and other:
        with db._connect() as conn:  # noqa: SLF001
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (other,))
        shutil.rmtree(_doc_dir(other), ignore_errors=True)
        db.update_document(doc_id, duplicate_of=None, dup_action="replaced", dup_message="已用本次上传替换旧版本")
        return {"status": "replaced", "removed": other}

    if action == "keep_existing" and other:
        with db._connect() as conn:  # noqa: SLF001
            conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        shutil.rmtree(_doc_dir(doc_id), ignore_errors=True)
        return {"status": "kept_existing", "removed": doc_id}

    db.update_document(doc_id, dup_action="keep_both", dup_message="已保留两个版本")
    return {"status": "kept_both"}


@router.delete("/{doc_id}")
def delete_document(doc_id: str) -> dict[str, str]:
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    with db._connect() as conn:  # noqa: SLF001 - 单条删除，无需额外封装
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    shutil.rmtree(_doc_dir(doc_id), ignore_errors=True)
    return {"status": "deleted", "doc_id": doc_id}
