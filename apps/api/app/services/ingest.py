"""入库管道：解析 → 指纹 → 去重判定 → 落库。

抽成独立服务，是因为"上传文件"和"按 arXiv ID 自动下钻入库"要走完全相同的流程，
差别只在字节从哪里来。路由层不应各写一遍。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from ..core import db
from ..core.config import get_settings
from ..models.schema import DocumentSummary, ParsedDocument
from . import dedupe
from .parser import PdfParser

logger = logging.getLogger(__name__)


def version_hint(file_name: str) -> str:
    import re

    m = re.search(r"v(\d+)", file_name or "", re.I)
    return f"v{m.group(1)}" if m else ""


def doc_dir(doc_id: str) -> Path:
    return get_settings().docs_dir / doc_id


def pool(exclude: str | None = None) -> list[dedupe.Fingerprint]:
    """加载库内全部指纹；老文档没有指纹文件时按需补算。"""
    out: list[dedupe.Fingerprint] = []
    for row in db.list_documents():
        doc_id = row["doc_id"]
        if doc_id == exclude:
            continue
        fp = dedupe.load_fingerprint(doc_dir(doc_id))
        if fp is None:
            payload = db.load_parsed(doc_id)
            if payload is None:
                continue
            parsed = ParsedDocument.model_validate(payload)
            fp = dedupe.build_fingerprint(parsed)
            dedupe.save_fingerprint(fp, doc_dir(doc_id))
        out.append(fp)
    return out


def store_document(doc_id: str, pdf_path: Path, file_name: str) -> DocumentSummary:
    settings = get_settings()
    uploaded_at = datetime.now(timezone.utc).isoformat()
    version = version_hint(file_name)

    try:
        parser = PdfParser(ocr_engine=settings.ocr_engine, max_pages_inline=settings.max_pages_inline)
        parsed = parser.parse(pdf_path, doc_id)
        parsed.file_name = file_name  # 落盘名是 original.pdf，对外保持原始文件名
        db.save_parsed(doc_id, parsed.model_dump())

        fp = dedupe.build_fingerprint(parsed)
        dedupe.save_fingerprint(fp, doc_dir(doc_id))

        match = dedupe.find_best_match(fp, pool(exclude=doc_id))
        rec = {"action": "", "message": ""}
        if match is not None:
            existing = db.get_document(match.doc_id)
            existing_version = (existing or {}).get("version_hint", "")
            rec = dedupe.recommend(version, existing_version, match)

        db.upsert_document(
            {
                "doc_id": doc_id,
                "file_name": file_name,
                "title": parsed.title or file_name,
                "authors": json.dumps(parsed.authors, ensure_ascii=False),
                "page_count": parsed.stats.page_count if parsed.stats else 0,
                "is_scanned": int(parsed.is_scanned),
                "layout": parsed.layout,
                "status": "ready",
                "error": "",
                "fingerprint": fp.simhash,
                "simhash": fp.simhash,
                "version_hint": version,
                "duplicate_of": match.doc_id if match else None,
                "dup_similarity": match.similarity if match else 0.0,
                "dup_verdict": match.verdict if match else "",
                "dup_action": rec["action"],
                "dup_message": rec["message"],
                "uploaded_at": uploaded_at,
            }
        )
        row = db.get_document(doc_id)
        return _summary(row or {})
    except HTTPException:
        raise
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
                "simhash": "",
                "version_hint": version,
                "dup_similarity": 0.0,
                "dup_verdict": "",
                "dup_action": "",
                "dup_message": "",
                "uploaded_at": uploaded_at,
            }
        )
        raise HTTPException(status_code=422, detail=f"解析失败: {exc}") from exc


def _summary(r: dict) -> DocumentSummary:
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
