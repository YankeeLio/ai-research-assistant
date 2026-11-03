"""文献管理：上传、列表、详情、解析结果读取、删除。"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..core import db
from ..core.config import get_settings
from ..models.schema import DocumentSummary, ParsedDocument
from ..services.parser import PdfParser

router = APIRouter(prefix="/documents", tags=["documents"])


def _summary_from_parsed(parsed: ParsedDocument, uploaded_at: str) -> DocumentSummary:
    return DocumentSummary(
        doc_id=parsed.doc_id,
        file_name=parsed.file_name,
        title=parsed.title or parsed.file_name,
        authors=parsed.authors,
        page_count=parsed.stats.page_count if parsed.stats else 0,
        is_scanned=parsed.is_scanned,
        layout=parsed.layout,
        uploaded_at=uploaded_at,
        status="ready",
    )


def _fingerprint(parsed: ParsedDocument) -> str:
    """正文指纹：取前 5 页正文（去空白、去数字）做 sha256。

    真正的语义去重（SimHash + 向量）在 services/dedupe.py 中实现，
    这里先提供稳定的粗筛键，保证重复上传能被立刻识别。
    """
    head = " ".join(parsed.page_texts[:5])
    normalized = re.sub(r"[\s\d\W]+", "", head.lower())[:5000]
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


def _parse_and_store(doc_id: str, pdf_path: Path, file_name: str) -> DocumentSummary:
    settings = get_settings()
    uploaded_at = datetime.now(timezone.utc).isoformat()
    try:
        parser = PdfParser(ocr_engine=settings.ocr_engine, max_pages_inline=settings.max_pages_inline)
        parsed = parser.parse(pdf_path, doc_id)
        parsed.file_name = file_name  # 落盘文件名是 original.pdf，对外保持用户原始文件名
        db.save_parsed(doc_id, parsed.model_dump())
        summary = _summary_from_parsed(parsed, uploaded_at)
        fp = _fingerprint(parsed)
        db.upsert_document(
            {
                "doc_id": doc_id,
                "file_name": file_name,
                "title": summary.title,
                "authors": __import__("json").dumps(summary.authors, ensure_ascii=False),
                "page_count": summary.page_count,
                "is_scanned": int(summary.is_scanned),
                "layout": summary.layout,
                "status": "ready",
                "error": "",
                "fingerprint": fp,
                "version_hint": _version_hint(file_name),
                "uploaded_at": uploaded_at,
            }
        )
        summary.content_fingerprint = fp
        summary.version_hint = _version_hint(file_name)
        return summary
    except Exception as exc:  # noqa: BLE001 - 解析失败要落库，前端才能提示
        db.upsert_document(
            {
                "doc_id": doc_id,
                "file_name": file_name,
                "title": file_name,
                "authors": "[]",
                "page_count": 0,
                "is_scanned": 0,
                "layout": "single",
                "status": "failed",
                "error": str(exc)[:500],
                "fingerprint": "",
                "version_hint": _version_hint(file_name),
                "uploaded_at": uploaded_at,
            }
        )
        raise HTTPException(status_code=422, detail=f"解析失败: {exc}") from exc


def _version_hint(file_name: str) -> str:
    m = re.search(r"v(\d+)", file_name, re.I)
    return f"v{m.group(1)}" if m else ""


@router.post("/upload", response_model=DocumentSummary)
async def upload_document(file: UploadFile = File(...)) -> DocumentSummary:
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

    return await run_in_threadpool(_parse_and_store, doc_id, pdf_path, file.filename or "untitled.pdf")


@router.get("", response_model=list[DocumentSummary])
def list_documents() -> list[DocumentSummary]:
    rows = db.list_documents()
    out: list[DocumentSummary] = []
    for r in rows:
        out.append(
            DocumentSummary(
                doc_id=r["doc_id"],
                file_name=r["file_name"],
                title=r["title"] or r["file_name"],
                authors=__import__("json").loads(r["authors"] or "[]"),
                page_count=r["page_count"],
                is_scanned=bool(r["is_scanned"]),
                layout=r["layout"],
                uploaded_at=r["uploaded_at"],
                status=r["status"],
                error=r["error"],
                content_fingerprint=r["fingerprint"],
                version_hint=r["version_hint"],
                duplicate_of=r["duplicate_of"],
            )
        )
    return out


@router.get("/{doc_id}", response_model=DocumentSummary)
def get_document(doc_id: str) -> DocumentSummary:
    r = db.get_document(doc_id)
    if not r:
        raise HTTPException(status_code=404, detail="文档不存在")
    return DocumentSummary(
        doc_id=r["doc_id"],
        file_name=r["file_name"],
        title=r["title"] or r["file_name"],
        authors=__import__("json").loads(r["authors"] or "[]"),
        page_count=r["page_count"],
        is_scanned=bool(r["is_scanned"]),
        layout=r["layout"],
        uploaded_at=r["uploaded_at"],
        status=r["status"],
        error=r["error"],
        content_fingerprint=r["fingerprint"],
        version_hint=r["version_hint"],
        duplicate_of=r["duplicate_of"],
    )


@router.get("/{doc_id}/parsed", response_model=ParsedDocument)
def get_parsed(doc_id: str) -> ParsedDocument:
    payload = db.load_parsed(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="解析结果不存在")
    return ParsedDocument.model_validate(payload)


@router.delete("/{doc_id}")
def delete_document(doc_id: str) -> dict[str, str]:
    settings = get_settings()
    if not db.get_document(doc_id):
        raise HTTPException(status_code=404, detail="文档不存在")
    with db._connect() as conn:  # noqa: SLF001 - 单条删除，无需额外封装
        conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    shutil.rmtree(settings.docs_dir / doc_id, ignore_errors=True)
    return {"status": "deleted", "doc_id": doc_id}
