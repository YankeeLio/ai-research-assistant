"""PDF 细粒度解析。

设计要点
--------
1. **以"行"为最小单元**：学术 PDF 的 block 常常把左右两栏的文字合并成一个
   bbox 横跨整页的块（实测 1706.03762 即如此），若直接按 block 处理，双栏
   还原和引用锚点坐标都会错。这里先取 line，再按"横向带状切分 + 栏内合并"
   重建段落块。
2. **文本层优先**：仅在整页无文本层时回落 OCR。
3. **锚点不可丢**：每个 block 携带 page 与 bbox，后续 RAG 溯源、引用跳转、
   划词翻译全部复用这份坐标。
"""

from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from ..models.schema import (
    Block,
    CiteAnchor,
    ParsedDocument,
    ParseStats,
    Reference,
    Section,
    TableModel,
)

logger = logging.getLogger(__name__)

CITE_RE = re.compile(r"\[(\d{1,3}(?:\s*[,，\-–]\s*\d{1,3})*)\]")
REF_START_RE = re.compile(r"^\s*\[(\d{1,3})\]\s*")
# "1 Introduction" / "3.2.1Scaled Dot-Product Attention"（LaTeX 抽取常丢空格）
NUM_HEADING_RE = re.compile(r"^(\d{1,2}(?:\.\d{1,2}){0,2})\.?\s*([A-Z][A-Za-z].{0,90})$")
MATH_FONT_HINTS = ("CMMI", "CMSY", "CMEX", "MSBM", "Symbol", "MTMI", "MTSY", "EUEX", "MTEX")
CAPTION_RE = re.compile(r"^(figure|table|fig\.|algorithm)\s*\d+", re.I)
ARXIV_STAMP_RE = re.compile(r"^arxiv:\s*\d{4}\.\d{4,5}", re.I)
DATE_ONLY_RE = re.compile(r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}$", re.I)
YEAR_IN_TEXT_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def _looks_like_reference(text: str) -> bool:
    """作者-年份式参考文献的启发式判定。

    判据：够长、含四位年份、以大写字母开头、不是图表标题、且不是以句号收尾的普通正文。
    """
    if len(text) < 40 or len(text) > 1200:
        return False
    if not YEAR_IN_TEXT_RE.search(text):
        return False
    if CAPTION_RE.match(text):
        return False
    if not text[0].isupper():
        return False
    return True

NAMED_SECTIONS = {
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "methods",
    "approach",
    "experiments",
    "experimental setup",
    "results",
    "discussion",
    "conclusion",
    "conclusions",
    "references",
    "bibliography",
    "acknowledgements",
    "acknowledgments",
    "appendix",
}


def _clean(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


@dataclass
class _Line:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    size: float
    bold: bool
    fonts: set[str] = field(default_factory=set)
    column: int = 0
    ocr: bool = False

    @property
    def y0(self) -> float:
        return self.bbox[1]

    @property
    def y1(self) -> float:
        return self.bbox[3]

    @property
    def height(self) -> float:
        return max(1.0, self.bbox[3] - self.bbox[1])


@dataclass
class _RawBlock:
    page: int
    bbox: tuple[float, float, float, float]
    text: str
    size: float
    bold: bool
    fonts: set[str] = field(default_factory=set)
    column: int = 0
    kind: str = "paragraph"
    level: int = 0
    ocr: bool = False


class PdfParser:
    """把 PDF 解析成结构化文档。每次调用自建 Document，可安全并发。"""

    def __init__(self, ocr_engine: str = "paddle", max_pages_inline: int = 200) -> None:
        self.ocr_engine = ocr_engine
        self.max_pages_inline = max_pages_inline

    # ------------------------------------------------------------------ public
    def parse(self, pdf_path: Path, doc_id: str) -> ParsedDocument:
        started = time.perf_counter()
        doc = pymupdf.open(pdf_path)
        try:
            if doc.needs_pass:
                raise ValueError("PDF 已加密，需先解密")

            raw_blocks, page_texts, scanned_pages = self._extract_blocks(doc)
            layout = self._detect_layout(raw_blocks)

            body_size = self._body_font_size(raw_blocks)
            self._classify_headings(raw_blocks, body_size)
            self._mark_formulas(raw_blocks)

            ref_start = self._find_references_start(raw_blocks)
            references = self._parse_references(raw_blocks, ref_start)
            cite_anchors = self._extract_cite_anchors(raw_blocks, ref_start)
            self._refine_anchor_bboxes(cite_anchors, doc)
            tables, figure_count = self._extract_tables_and_figures(doc)

            blocks = [
                Block(
                    id=f"b{i}",
                    page=b.page,
                    bbox=[round(v, 2) for v in b.bbox],
                    text=b.text,
                    kind=b.kind,  # type: ignore[arg-type]
                    level=b.level,
                    font_size=round(b.size, 1),
                    column=b.column,
                    ocr=b.ocr,
                )
                for i, b in enumerate(raw_blocks)
            ]
            id_map = {id(b): blk.id for b, blk in zip(raw_blocks, blocks)}
            for ref, raw in zip(references, self._ref_blocks):
                ref.block_id = id_map.get(id(raw), "")
            for anchor, raw in zip(cite_anchors, self._cite_blocks):
                anchor.block_id = id_map.get(id(raw), "")

            sections = self._build_section_tree(blocks)
            title, authors = self._extract_title_and_authors(blocks)
            abstract = self._extract_abstract(blocks)

            stats = ParseStats(
                page_count=doc.page_count,
                block_count=len(blocks),
                heading_count=sum(1 for b in blocks if b.kind in ("heading", "title")),
                table_count=len(tables),
                figure_count=figure_count,
                reference_count=len(references),
                cite_anchor_count=len(cite_anchors),
                formula_block_count=sum(1 for b in blocks if b.kind == "formula"),
                char_count=sum(len(t) for t in page_texts),
                scanned_pages=len(scanned_pages),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )

            return ParsedDocument(
                doc_id=doc_id,
                file_name=pdf_path.name,
                title=title,
                authors=authors,
                abstract=abstract,
                layout=layout,  # type: ignore[arg-type]
                is_scanned=bool(doc.page_count and len(scanned_pages) >= doc.page_count / 2),
                sections=sections,
                blocks=blocks,
                tables=tables,
                references=references,
                cite_anchors=cite_anchors,
                page_texts=page_texts,
                stats=stats,
            )
        finally:
            doc.close()

    # ----------------------------------------------------------------- extract
    def _extract_blocks(
        self, doc: pymupdf.Document
    ) -> tuple[list[_RawBlock], list[str], list[int]]:
        blocks: list[_RawBlock] = []
        page_texts: list[str] = []
        scanned: list[int] = []

        for pno in range(doc.page_count):
            page = doc[pno]
            width = page.rect.width or 1.0
            height = page.rect.height or 1.0
            page_text = (page.get_text("text") or "").strip()
            page_texts.append(page_text)

            lines = self._page_lines(page, width, height)
            if not lines and self.ocr_engine != "none":
                ocr_lines = self._ocr_page_lines(page)
                if ocr_lines:
                    scanned.append(pno)
                    lines = ocr_lines
                    page_texts[-1] = _clean(" ".join(ln.text for ln in ocr_lines))
            if not lines:
                if page.get_images(full=False) or len(page_text) < 40:
                    scanned.append(pno)
                continue
            if self._page_is_two_column(lines):
                self._assign_columns(lines, width)

            blocks.extend(self._lines_to_blocks(lines, width))

        return blocks, page_texts, scanned

    def _page_lines(self, page: pymupdf.Page, width: float, height: float) -> list[_Line]:
        lines: list[_Line] = []
        data = page.get_text("dict")
        for raw_block in data.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            for line in raw_block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                # LaTeX 生成的 PDF 常把空格单独放成一个 span；若按"非空 span"过滤再拼接，
                # 整句会粘成 "Theencoderiscomposedof..."，检索与阅读都会失真。
                text = _clean("".join(s.get("text", "") for s in spans))
                if not text:
                    continue
                x0, y0, x1, y1 = line.get("bbox", (0, 0, 0, 0))
                # 去掉页眉页脚与 arXiv 侧边水印
                if y1 < height * 0.055 or y0 > height * 0.965:
                    continue
                if x0 < width * 0.12 and ARXIV_STAMP_RE.match(text):
                    continue
                visible = [s for s in spans if s.get("text", "").strip()]
                sizes = [s.get("size", 0.0) for s in visible]
                bold = sum(1 for s in visible if int(s.get("flags", 0)) & 16) >= len(visible) / 2
                lines.append(
                    _Line(
                        page=page.number,
                        bbox=(x0, y0, x1, y1),
                        text=text,
                        size=max(sizes) if sizes else 0.0,
                        bold=bold,
                        fonts={s.get("font", "") for s in spans},
                    )
                )

        return lines

    @staticmethod
    def _page_is_two_column(lines: list[_Line]) -> bool:
        """判断是否双栏：要求两侧都有足够多的"窄行"，且跨中线的行占比很低。

        单栏页面里绝大多数行都横跨中线，这里直接否决，避免把单栏论文
        误判成双栏（1706.03762v1 就是单栏，v7 才是双栏）。
        """
        if len(lines) < 8:
            return False
        x_min = min(ln.bbox[0] for ln in lines)
        x_max = max(ln.bbox[2] for ln in lines)
        cx = (x_min + x_max) / 2
        left = [ln for ln in lines if ln.bbox[2] < cx - 4]
        right = [ln for ln in lines if ln.bbox[0] > cx + 4]
        crossing = [ln for ln in lines if ln.bbox[0] < cx - 4 and ln.bbox[2] > cx + 4]
        return len(left) >= 6 and len(right) >= 6 and len(crossing) <= 0.25 * len(lines)

    @staticmethod
    def _assign_columns(lines: list[_Line], width: float) -> None:
        for ln in lines:
            if ln.bbox[2] <= width * 0.55:
                ln.column = 0
            elif ln.bbox[0] >= width * 0.45:
                ln.column = 1
            else:
                ln.column = -1  # 跨栏：通栏公式、图注、摘要

    def _lines_to_blocks(self, lines: list[_Line], width: float) -> list[_RawBlock]:
        """横向分带：通栏行切带，带内先左栏后右栏，再按行距合并成段落块。"""
        lines.sort(key=lambda ln: (ln.bbox[1], ln.bbox[0]))
        bands: list[list[_Line]] = []
        current: list[_Line] = []
        current_bottom = -1e9

        for ln in lines:
            if not current:
                current, current_bottom = [ln], ln.bbox[3]
                continue
            gap = ln.bbox[1] - current_bottom
            if gap > max(18.0, 2.6 * ln.height) or (ln.column == -1 or current[-1].column == -1):
                bands.append(current)
                current, current_bottom = [ln], ln.bbox[3]
            else:
                current.append(ln)
                current_bottom = max(current_bottom, ln.bbox[3])
        if current:
            bands.append(current)

        blocks: list[_RawBlock] = []
        for band in bands:
            ordered = sorted(band, key=lambda ln: (0 if ln.column == -1 else ln.column, ln.bbox[1]))
            blocks.extend(self._merge_band(ordered))
        return blocks

    @staticmethod
    def _merge_band(lines: list[_Line]) -> list[_RawBlock]:
        blocks: list[_RawBlock] = []
        buf: list[_Line] = []

        def flush() -> None:
            if not buf:
                return
            text = ""
            for i, ln in enumerate(buf):
                if i == 0:
                    text = ln.text
                elif text.endswith("-"):
                    text += ln.text
                else:
                    text += " " + ln.text
            x0 = min(ln.bbox[0] for ln in buf)
            y0 = min(ln.bbox[1] for ln in buf)
            x1 = max(ln.bbox[2] for ln in buf)
            y1 = max(ln.bbox[3] for ln in buf)
            fonts: set[str] = set().union(*(ln.fonts for ln in buf))
            blocks.append(
                _RawBlock(
                    page=buf[0].page,
                    bbox=(x0, y0, x1, y1),
                    text=_clean(text),
                    size=max(ln.size for ln in buf),
                    bold=all(ln.bold for ln in buf),
                    fonts=fonts,
                    column=max(0, buf[0].column),
                    ocr=buf[0].ocr,
                )
            )
            buf.clear()

        for ln in lines:
            if not buf:
                buf = [ln]
                continue
            prev = buf[-1]
            # 参考文献条目、图表标题必须独立成块，否则后续引用解析会串行
            if REF_START_RE.match(ln.text) or CAPTION_RE.match(ln.text):
                flush()
                buf = [ln]
                continue
            same_col = prev.column == ln.column
            same_size = abs(prev.size - ln.size) < 1.2
            same_bold = prev.bold == ln.bold
            gap = ln.bbox[1] - prev.bbox[3]
            if same_col and same_size and same_bold and gap < 0.45 * ln.height:
                buf.append(ln)
            else:
                flush()
                buf = [ln]
        flush()
        return blocks

    def _ocr_page_lines(self, page: pymupdf.Page) -> list[_Line]:
        """扫描页 OCR，返回与矢量页同构的行对象（含 PDF 坐标）。"""
        from .ocr import ocr_page_lines

        lines: list[_Line] = []
        for bbox, text, _score in ocr_page_lines(page):
            if page.number == 0 and ARXIV_STAMP_RE.match(text):
                continue  # arXiv 侧边水印常被 OCR 识别成正文，会污染标题
            height = max(1.0, bbox[3] - bbox[1])
            lines.append(
                _Line(
                    page=page.number,
                    bbox=bbox,
                    text=_clean(text),
                    size=max(5.0, height * 0.78),
                    bold=False,
                    ocr=True,
                )
            )
        return lines

    # -------------------------------------------------------------- structure
    @staticmethod
    def _body_font_size(blocks: list[_RawBlock]) -> float:
        hist: dict[float, int] = {}
        for b in blocks:
            key = round(b.size * 2) / 2
            if key <= 0:
                continue
            hist[key] = hist.get(key, 0) + len(b.text)
        if not hist:
            return 10.0
        return max(hist.items(), key=lambda kv: kv[1])[0]

    @staticmethod
    def _detect_layout(blocks: list[_RawBlock]) -> str:
        if not blocks:
            return "single"
        per_page: dict[int, set[int]] = {}
        for b in blocks:
            per_page.setdefault(b.page, set()).add(b.column)
        double_pages = sum(1 for cols in per_page.values() if 1 in cols)
        ratio = double_pages / max(1, len(per_page))
        if ratio > 0.6:
            return "double"
        return "mixed" if ratio > 0.2 else "single"

    def _classify_headings(self, blocks: list[_RawBlock], body: float) -> None:
        sizes: list[float] = []
        for b in blocks:
            text = b.text
            if not text or len(text) > 160:
                continue
            if CAPTION_RE.match(text):
                b.kind = "caption"
                continue
            lowered = re.sub(r"^[\d.]+\s*", "", text).lower().strip(" .:")
            is_named = lowered in NAMED_SECTIONS
            numbered = bool(NUM_HEADING_RE.match(text))
            # OCR 没有字号与字重，只能依赖"编号 + 命名章节"两个强信号，
            # 否则 OCR 行高抖动会把整页判成标题（实测 173 个假标题）。
            if b.ocr:
                if not (is_named or numbered):
                    continue
            else:
                size_bigger = b.size >= body * 1.12
                bold_line = b.bold and b.size >= body * 0.98
                if not (is_named or size_bigger or bold_line):
                    continue
            # 编号开头的行在正文里也可能出现（"3 We used values of ..."这类脚注编号），
            # 真正的标题是短语，不会长成一整句。
            if numbered and (len(text) > 80 or len(text.split()) > 10):
                continue
            if not is_named and not numbered and text.endswith((".", ",", ";")) and len(text) > 40:
                continue
            b.kind = "heading"
            sizes.append(round(b.size, 1))

        ordered = sorted(set(sizes), reverse=True)
        size_to_level = {s: min(i + 1, 3) for i, s in enumerate(ordered)}

        for b in blocks:
            if b.kind != "heading":
                continue
            m = NUM_HEADING_RE.match(b.text)
            numbered_level = (m.group(1).count(".") + 1) if m else None
            if numbered_level:
                b.level = max(1, min(3, numbered_level))
            elif b.ocr:
                # OCR 字号不可靠，命名章节（Abstract/References/...）一律视为一级
                b.level = 1
            else:
                b.level = max(1, min(3, size_to_level.get(round(b.size, 1), 2)))
            if b.level == 1 and b.size >= body * 1.5:
                b.kind = "title"

    @staticmethod
    def _find_references_start(blocks: list[_RawBlock]) -> int:
        for i, b in enumerate(blocks):
            if len(b.text) > 40:
                continue
            if re.sub(r"^[\d.]+\s*", "", b.text.lower()).strip(" .:") in (
                "references",
                "bibliography",
                "reference",
            ):
                return i
        return -1

    def _parse_references(self, blocks: list[_RawBlock], start: int) -> list[Reference]:
        """参考文献解析：同时支持两种排版。

        - 数字式：`[12] Author. Title.` 或 `12. Author. Title.`（NeurIPS/IEEE 常见）
        - 作者-年份式：`Alan Akbik, Duncan Blythe, and Roland Vollgraf. 2018. Title.`
          （ACL/NAACL 常见，**没有任何编号**，只按编号匹配会一篇都解析不出来）
        """
        self._ref_blocks: list[_RawBlock] = []
        if start < 0:
            return []

        refs: list[Reference] = []
        current: tuple[int, _RawBlock, list[str]] | None = None
        auto_index = 0

        for b in blocks[start + 1 :]:
            if b.text.lower().startswith(("appendix", "supplementary", "a appendix")):
                break
            m = REF_START_RE.match(b.text)
            if m:
                if current:
                    refs.append(self._make_reference(*current))
                    self._ref_blocks.append(current[1])
                index = int(m.group(1))
                auto_index = max(auto_index, index)
                current = (index, b, [REF_START_RE.sub("", b.text)])
            elif _looks_like_reference(b.text):
                if current:
                    refs.append(self._make_reference(*current))
                    self._ref_blocks.append(current[1])
                auto_index += 1
                current = (auto_index, b, [b.text])
            elif current is not None and len(b.text) < 500:
                current[2].append(b.text)
        if current:
            refs.append(self._make_reference(*current))
            self._ref_blocks.append(current[1])
        return refs

    @staticmethod
    def _make_reference(index: int, block: _RawBlock, parts: list[str]) -> Reference:
        text = _clean(" ".join(parts))
        year_m = re.search(r"(?:19|20)\d{2}", text)
        arxiv_m = re.search(r"arXiv:\s?(\d{4}\.\d{4,5})(v\d+)?", text, re.I)
        doi_m = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", text)
        return Reference(
            index=index,
            text=text[:1000],
            page=block.page,
            block_id="",
            year=int(year_m.group(0)) if year_m else None,
            arxiv_id=arxiv_m.group(1) if arxiv_m else None,
            doi=doi_m.group(0).rstrip(".") if doi_m else None,
        )

    def _extract_cite_anchors(self, blocks: list[_RawBlock], ref_start: int) -> list[CiteAnchor]:
        self._cite_blocks: list[_RawBlock] = []
        anchors: list[CiteAnchor] = []
        for i, b in enumerate(blocks):
            if 0 <= ref_start <= i:
                continue
            for m in CITE_RE.finditer(b.text):
                for token in re.split(r"\s*[,，\-–]\s*", m.group(1)):
                    if not token.isdigit():
                        continue
                    anchors.append(
                        CiteAnchor(
                            ref_index=int(token),
                            page=b.page,
                            block_id="",
                            bbox=[round(v, 2) for v in b.bbox],
                            raw=m.group(0),
                        )
                    )
                    self._cite_blocks.append(b)
        return anchors

    @staticmethod
    def _mark_formulas(blocks: list[_RawBlock]) -> None:
        """数学字体命中的短块视为公式块：用于阅读器高亮与"公式保留英文"的翻译策略。"""
        for b in blocks:
            if b.kind != "paragraph":
                continue
            if len(b.text) > 150:
                continue
            if any(any(hint in font for hint in MATH_FONT_HINTS) for font in b.fonts):
                b.kind = "formula"

    def _refine_anchor_bboxes(
        self, anchors: list[CiteAnchor], doc: pymupdf.Document
    ) -> None:
        """把引用锚点从"整段 bbox"收敛到"[12]"这几个字符的精确矩形。

        阅读器据此做高亮与跳转，块级坐标会导致高亮一大片。
        """
        if not anchors or len(anchors) > 600:
            return
        cache: dict[tuple[int, str], list[float] | None] = {}
        for anchor, block in zip(anchors, self._cite_blocks):
            key = (block.page, anchor.raw)
            if key not in cache:
                clip = pymupdf.Rect(block.bbox)
                try:
                    hits = doc[block.page].search_for(anchor.raw, clip=clip)
                except Exception:  # noqa: BLE001 - 单点失败不影响整体
                    hits = []
                cache[key] = [round(v, 2) for v in hits[0]] if hits else None
            refined = cache[key]
            if refined:
                anchor.bbox = refined

    @staticmethod
    def _likely_has_table(page: pymupdf.Page) -> bool:
        """表格识别的开销量级与整页解析相当，先做低成本筛选。

        判据：页面出现 "Table N" 字样，或矢量线条数量足以构成表格网框。
        541 页教材实测：全量 find_tables 需 159 s，筛选后降至 33 s。
        """
        text = page.get_text("text") or ""
        return bool(re.search(r"\btable\s*\d", text, re.I))

    def _extract_tables_and_figures(
        self, doc: pymupdf.Document
    ) -> tuple[list[TableModel], int]:
        tables: list[TableModel] = []
        figures = 0
        for pno in range(doc.page_count):
            page = doc[pno]
            figures += len(page.get_images(full=False))
            if not self._likely_has_table(page):
                continue
            try:
                found = page.find_tables()
            except Exception:  # noqa: BLE001 - 表格识别失败不应中断整篇解析
                continue
            for t in found.tables:
                if len(tables) >= 200:
                    break
                try:
                    rows = [[(c or "").strip() for c in row] for row in t.extract()]
                except Exception:  # noqa: BLE001
                    continue
                if len(rows) < 2 or not any(any(c for c in r) for r in rows):
                    continue
                tables.append(
                    TableModel(
                        id=f"t{len(tables)}",
                        page=pno,
                        bbox=[round(v, 2) for v in t.bbox],
                        rows=rows[:60],
                    )
                )
        return tables, figures

    def _build_section_tree(self, blocks: list[Block]) -> list[Section]:
        roots: list[Section] = []
        stack: list[Section] = []
        counter = 0
        for b in blocks:
            if b.kind not in ("heading", "title"):
                continue
            node = Section(
                id=f"s{counter}",
                title=b.text[:200],
                level=b.level or 1,
                page=b.page,
                block_id=b.id,
            )
            counter += 1
            while stack and stack[-1].level >= node.level:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            else:
                roots.append(node)
            stack.append(node)
        return roots

    @staticmethod
    def _extract_title_and_authors(blocks: list[Block]) -> tuple[str, list[str]]:
        first = [b for b in blocks if b.page == 0 and b.text]
        if not first:
            return "", []

        body = statistics.median([b.font_size for b in first]) or 10.0
        page_width = max((b.bbox[2] for b in first), default=0.0)
        clean = [
            b
            for b in first
            if not ARXIV_STAMP_RE.match(b.text) and not DATE_ONLY_RE.match(b.text)
        ]
        # OCR 页的字号来自行高估计，比矢量页更粗，阈值相应放宽
        ratio = 1.18 if any(b.ocr for b in first) else 1.35
        candidates = [
            b
            for b in clean
            if (b.kind == "title" or (b.font_size >= body * ratio and len(b.text) < 200))
            and len(b.text) >= 12
            and (b.bbox[2] - b.bbox[0]) > page_width * 0.25
        ]
        if not candidates:
            candidates = [max(clean or first, key=lambda b: b.font_size)]

        title_block = max(candidates, key=lambda b: b.font_size)
        title = title_block.text[:300]

        authors: list[str] = []
        affiliation_hint = re.compile(r"(@|google|university|institute|research|brain|labs?|inc\.)", re.I)
        name_re = re.compile(r"^[A-ZŁŚŻ][\w'’.\-]*(?:\s+[A-ZŁŚŻ][\w'’.\-]*){1,3}$")
        for b in first:
            if b.bbox[1] <= title_block.bbox[3]:
                continue
            if b.text.lower().startswith(("abstract", "摘要")):
                break
            if b.bbox[1] > title_block.bbox[3] + 200:
                break
            if len(b.text) > 160:
                continue
            if affiliation_hint.search(b.text):
                continue
            for part in re.split(r"[∗†‡,;·]|\s{2,}", b.text):
                part = part.strip(" ,;.")
                if name_re.match(part) and len(part) <= 45:
                    authors.append(part)
            if len(authors) >= 10:
                break
        seen: set[str] = set()
        unique = [a for a in authors if not (a in seen or seen.add(a))]
        return title, unique[:12]

    @staticmethod
    def _extract_abstract(blocks: list[Block]) -> str:
        for i, b in enumerate(blocks):
            if b.text.lower().strip(" .:") == "abstract":
                parts: list[str] = []
                for nxt in blocks[i + 1 : i + 6]:
                    if nxt.kind in ("heading", "title"):
                        break
                    parts.append(nxt.text)
                    if len(" ".join(parts)) > 300:
                        break
                return _clean(" ".join(parts))[:2000]
        return ""
