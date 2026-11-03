"""解析结果的数据契约。

前端阅读器、RAG 溯源、图谱构建全部依赖这里的字段，因此锚点信息
（页码 + bbox + block_id）是一等公民，不允许在后续环节丢失。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

BlockKind = Literal["title", "heading", "paragraph", "reference", "formula", "caption", "table"]


class Block(BaseModel):
    id: str
    page: int  # 从 0 开始
    bbox: list[float]  # [x0, y0, x1, y1]，PDF 用户坐标
    text: str
    kind: BlockKind = "paragraph"
    level: int = 0  # 标题层级，0 表示非标题
    font_size: float = 0.0
    column: int = 0  # 0=左栏/单栏 1=右栏


class Section(BaseModel):
    """标题树节点；children 递归。"""

    id: str
    title: str
    level: int
    page: int
    block_id: str
    children: list["Section"] = Field(default_factory=list)


class TableModel(BaseModel):
    id: str
    page: int
    bbox: list[float]
    rows: list[list[str]]
    caption: str = ""


class Reference(BaseModel):
    index: int  # 文献序号，如 [11] 中的 11
    text: str
    page: int
    block_id: str
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None


class CiteAnchor(BaseModel):
    """正文引用标记 [11] 的位置，用于 References 双向跳转。"""

    ref_index: int
    page: int
    block_id: str
    bbox: list[float]
    raw: str


class ParseStats(BaseModel):
    page_count: int
    block_count: int
    heading_count: int
    table_count: int
    figure_count: int
    reference_count: int
    cite_anchor_count: int
    formula_block_count: int
    char_count: int
    scanned_pages: int
    elapsed_ms: int = 0


class ParsedDocument(BaseModel):
    doc_id: str
    file_name: str
    title: str = ""
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    layout: Literal["single", "double", "mixed"] = "single"
    is_scanned: bool = False
    sections: list[Section] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    tables: list[TableModel] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    cite_anchors: list[CiteAnchor] = Field(default_factory=list)
    page_texts: list[str] = Field(default_factory=list)
    stats: ParseStats | None = None


class DocumentSummary(BaseModel):
    """列表接口用的轻量视图，不含数万条 block。"""

    doc_id: str
    file_name: str
    title: str
    authors: list[str]
    page_count: int
    is_scanned: bool
    layout: str
    uploaded_at: str
    status: Literal["parsing", "ready", "failed"] = "ready"
    error: str = ""

    # 去重与版本
    content_fingerprint: str = ""
    version_hint: str = ""
    duplicate_of: str | None = None
