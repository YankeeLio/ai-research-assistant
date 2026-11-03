"""分块：把解析出的 block 序列切成可检索的语义单元。

原则
----
1. **不切断公式与表格**：公式块与表格说明行尽量与上下文同块。
2. **继承章节路径**：每块记录 `section_path`（如 "3 Model Architecture / 3.2 Attention"），
   问答时既能按块检索，也能回答"第 3.2 节说了什么"这类结构性问题。
3. **保留溯源坐标**：块持有 page 与 block_ids，答案引用可直接回到原文。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from ..models.schema import Block, ParsedDocument


@dataclass
class Chunk:
    id: str
    doc_id: str
    text: str
    page: int
    block_ids: list[str] = field(default_factory=list)
    section_path: str = ""
    kind: str = "body"  # body | reference | table | abstract

    @property
    def char_count(self) -> int:
        return len(self.text)


def chunk_document(
    parsed: ParsedDocument, size: int = 800, overlap: int = 120
) -> list[Chunk]:
    """按 block 聚合分块，块内保持原始阅读顺序。"""
    chunks: list[Chunk] = []
    path_stack: list[tuple[int, str]] = []
    buf: list[Block] = []
    buf_len = 0

    def current_path() -> str:
        return " / ".join(title for _, title in path_stack)

    def flush() -> None:
        nonlocal buf, buf_len
        if not buf:
            return
        text = " ".join(b.text for b in buf).strip()
        if not text:
            buf, buf_len = [], 0
            return
        digest = hashlib.sha1(f"{parsed.doc_id}:{buf[0].id}:{text[:64]}".encode()).hexdigest()[:12]
        kind = "reference" if all(b.kind == "reference" for b in buf) else "body"
        chunks.append(
            Chunk(
                id=f"c{digest}",
                doc_id=parsed.doc_id,
                text=text,
                page=buf[0].page,
                block_ids=[b.id for b in buf],
                section_path=current_path(),
                kind=kind,
            )
        )
        # 尾部重叠：保留最后若干 block 作为下一块开头，避免跨块语义断裂
        if overlap > 0 and len(buf) > 1:
            tail: list[Block] = []
            tail_len = 0
            for b in reversed(buf):
                if tail_len >= overlap:
                    break
                tail.insert(0, b)
                tail_len += len(b.text)
            buf, buf_len = tail, tail_len
        else:
            buf, buf_len = [], 0

    for block in parsed.blocks:
        if block.kind in ("heading", "title"):
            flush()
            level = max(1, block.level)
            while path_stack and path_stack[-1][0] >= level:
                path_stack.pop()
            path_stack.append((level, block.text[:80]))
            continue
        if block.kind == "reference":
            flush()
            chunks.append(
                Chunk(
                    id=f"c{hashlib.sha1(f'{parsed.doc_id}:ref:{block.id}'.encode()).hexdigest()[:12]}",
                    doc_id=parsed.doc_id,
                    text=block.text,
                    page=block.page,
                    block_ids=[block.id],
                    section_path="References",
                    kind="reference",
                )
            )
            continue
        if buf_len + len(block.text) > size:
            flush()
        buf.append(block)
        buf_len += len(block.text)

    flush()
    _attach_tables(chunks, parsed)
    return chunks


def _attach_tables(chunks: list[Chunk], parsed: ParsedDocument) -> None:
    """表格单独成块：行内单元格用 " | " 连接，便于关键词与数值检索。"""
    for table in parsed.tables:
        rows = [" | ".join(cell for cell in row if cell) for row in table.rows]
        text = "\n".join(r for r in rows if r.strip())
        if not text:
            continue
        chunks.append(
            Chunk(
                id=f"t{hashlib.sha1(f'{parsed.doc_id}:{table.id}'.encode()).hexdigest()[:12]}",
                doc_id=parsed.doc_id,
                text=text,
                page=table.page,
                block_ids=[table.id],
                section_path="Table",
                kind="table",
            )
        )
