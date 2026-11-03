"""SQLite 持久层：只存元数据，解析结果以 JSON 落盘（便于前端整块读取与调试）。"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..core.config import get_settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id      TEXT PRIMARY KEY,
    file_name   TEXT NOT NULL,
    title       TEXT DEFAULT '',
    authors     TEXT DEFAULT '[]',
    page_count  INTEGER DEFAULT 0,
    is_scanned  INTEGER DEFAULT 0,
    layout      TEXT DEFAULT 'single',
    status      TEXT DEFAULT 'ready',
    error       TEXT DEFAULT '',
    fingerprint TEXT DEFAULT '',
    version_hint TEXT DEFAULT '',
    duplicate_of TEXT DEFAULT NULL,
    uploaded_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    db = get_settings().data_dir / "sciloom.db"
    conn = sqlite3.connect(db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def upsert_document(row: dict[str, Any]) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    with _connect() as conn:
        conn.execute(f"INSERT OR REPLACE INTO documents ({cols}) VALUES ({marks})", list(row.values()))


def list_documents() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    return [dict(r) for r in rows]


def get_document(doc_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    return dict(row) if row else None


def update_document(doc_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE documents SET {sets} WHERE doc_id = ?", [*fields.values(), doc_id])


def save_parsed(doc_id: str, payload: dict[str, Any]) -> Path:
    path = get_settings().docs_dir / doc_id / "parsed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def load_parsed(doc_id: str) -> dict[str, Any] | None:
    path = get_settings().docs_dir / doc_id / "parsed.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
