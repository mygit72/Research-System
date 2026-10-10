"""Layout-aware PDF parsing with PyMuPDF.

Per page:
1. Decide whether the page has a usable text layer; otherwise OCR it (if available).
2. Extract styled lines (font size, boldness, math fonts, bbox), splitting
   blocks where the style changes (a heading glued to its first paragraph).
3. Detect tables (ruled, then booktabs-style for pages with a "Table N" caption)
   and drop the text blocks inside them; figures from images / vector drawings.
4. Order blocks for reading: detect two-column layouts and interleave
   full-width blocks (title, wide figures) correctly.

Across pages: remove running headers/footers and page numbers, and capture the
arXiv margin stamp. The PDF outline (bookmarks), when present, is passed on as
authoritative heading information.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.ingestion.cleaning import clean_text
from app.services.ingestion.native import pymupdf
from app.services.ingestion.ocr import OCRProvider
from app.services.ingestion.parsers.base import ParseError, ProgressCallback, noop_progress
from app.services.ingestion.parsers.common import CAPTION_RE, table_to_markdown
from app.services.ingestion.types import (
    BBox,
    BlockKind,
    DocumentFormat,
    PageInfo,
    RawDocument,
    RawFigure,
    RawTable,
    TextBlock,
)

MIN_TEXT_CHARS = 40  # below this a page is treated as having no text layer
MARGIN_FRACTION = 0.08  # top/bottom band searched for running headers/footers
EQUATION_NUMBER_RE = re.compile(r"\((\d+[a-z]?)\)\s*$")
MATH_FONT_RE = re.compile(r"cmmi|cmsy|cmex|msbm|math|symbol|stix|cambria math|euler|rsfs", re.I)
MATH_CHARS = set("=+−-×·∑∏∫∂∇√∞≈≠≤≥∈∉⊂⊆∪∩∀∃λμσθαβγδεπφψωΣΠΔΩ^_{}|‖⟨⟩")
TEXT_FLAGS = (pymupdf.TEXTFLAGS_DICT | pymupdf.TEXT_DEHYPHENATE) & ~pymupdf.TEXT_PRESERVE_IMAGES


@dataclass(slots=True)
class _Line:
    text: str
    bbox: BBox
    size: float
    bold: bool
    math_ratio: float


class PDFParser:
    name = "pymupdf"
    formats = frozenset({DocumentFormat.PDF})

    def __init__(self, ocr: OCRProvider, detect_tables: bool = True) -> None:
        self.ocr = ocr
        self.detect_tables = detect_tables

    def parse(self, path: Path, progress: ProgressCallback | None = None) -> RawDocument:
        progress = progress or noop_progress
        try:
            doc = pymupdf.open(path)
        except Exception as exc:
            raise ParseError(
                "We couldn't open this PDF. The file may be corrupted.", detail=repr(exc)
            ) from exc
        with doc:
            if doc.needs_pass:
                raise ParseError(
                    "This PDF is password-protected.",
                    detail="encrypted document",
                )
            if doc.page_count == 0:
                raise ParseError("This PDF has no pages.")
            return self._parse_document(doc, progress)

    # ------------------------------------------------------------------ document

    def _parse_document(self, doc: pymupdf.Document, progress: ProgressCallback) -> RawDocument:
        total = doc.page_count
        pages: list[PageInfo] = []
        per_page_blocks: list[list[TextBlock]] = []
        tables: list[RawTable] = []
        figures: list[RawFigure] = []
        warnings: list[str] = []
        needs_ocr_pages: list[int] = []
        arxiv_stamp: str | None = None

        for index, page in enumerate(doc):
            number = index + 1
            progress("parsing", index / total, f"Extracting page {number} of {total}")
            info = PageInfo(number=number, width=page.rect.width, height=page.rect.height)

            textpage = page.get_textpage(flags=TEXT_FLAGS)
            native_chars = len(page.get_text("text", textpage=textpage).strip())
            if native_chars < MIN_TEXT_CHARS and _has_visual_content(page):
                if self.ocr.available():
                    progress("ocr", index / total, f"Running OCR on page {number} of {total}")
                    try:
                        textpage = self.ocr.page_textpage(page)
                        info.used_ocr = True
                    except Exception as exc:  # OCR failure on one page shouldn't kill the doc
                        warnings.append(f"OCR failed on page {number}: {type(exc).__name__}")
                else:
                    needs_ocr_pages.append(number)

            page_dict = page.get_text("dict", textpage=textpage, flags=TEXT_FLAGS)
            blocks, stamp = self._page_blocks(page_dict, number, info)
            arxiv_stamp = arxiv_stamp or stamp

            page_tables: list[RawTable] = []
            if self.detect_tables and not info.used_ocr:
                has_table_caption = any(
                    b.kind == BlockKind.CAPTION and b.text.lower().startswith("table")
                    for b in blocks
                )
                page_tables = _find_tables(page, number, has_table_caption)
            blocks = _drop_blocks_inside(blocks, [t.bbox for t in page_tables if t.bbox])
            for table in page_tables:
                blocks.append(
                    TextBlock(
                        text=table_to_markdown(table.rows),
                        page=number,
                        bbox=table.bbox,
                        kind=BlockKind.TABLE,
                    )
                )
            tables.extend(page_tables)
            table_boxes = [t.bbox for t in page_tables if t.bbox]
            figures.extend(
                f
                for f in _find_figures(page, number)
                if not any(f.bbox and _overlap(f.bbox, t) > 0.5 for t in table_boxes)
            )

            per_page_blocks.append(_reading_order(blocks, info.width or 612.0))
            pages.append(info)

        _remove_running_headers(per_page_blocks, pages)
        blocks = [block for page_blocks in per_page_blocks for block in page_blocks]

        if needs_ocr_pages:
            if len(needs_ocr_pages) == total:
                raise ParseError(
                    "This PDF appears to be scanned (it has no text layer) and OCR isn't "
                    "available on this server.",
                    detail="tesseract unavailable; all pages image-only",
                )
            warnings.append(
                f"{len(needs_ocr_pages)} page(s) look scanned and couldn't be read because "
                "OCR isn't available: " + ", ".join(map(str, needs_ocr_pages[:20]))
            )
        if not any(b.text.strip() for b in blocks):
            raise ParseError("We couldn't find any readable text in this PDF.")

        metadata = {k: v for k, v in (doc.metadata or {}).items() if isinstance(v, str) and v}
        if arxiv_stamp:
            metadata["arxiv_stamp"] = arxiv_stamp
        outline = [
            {"level": level, "title": title, "page": page_no}
            for level, title, page_no, *_ in doc.get_toc(simple=True)
        ]
        progress("parsing", 1.0, f"Extracted {total} pages")
        return RawDocument(
            format=DocumentFormat.PDF,
            pages=pages,
            blocks=blocks,
            tables=tables,
            figures=figures,
            embedded_metadata=metadata,
            warnings=warnings,
            paginated=True,
            parser=f"{self.name}-{pymupdf.VersionBind}",
            outline=outline,
        )

    # ---------------------------------------------------------------------- page

    def _page_blocks(
        self, page_dict: dict[str, Any], number: int, info: PageInfo
    ) -> tuple[list[TextBlock], str | None]:
        blocks: list[TextBlock] = []
        stamp: str | None = None
        for raw_block in page_dict.get("blocks", []):
            if raw_block.get("type") != 0:
                continue
            lines: list[_Line] = []
            for raw_line in raw_block.get("lines", []):
                line = _make_line(raw_line)
                if line is None:
                    continue
                direction = raw_line.get("dir", (1, 0))
                if abs(direction[0]) < 0.5:  # rotated text: margin stamps
                    if "arxiv" in line.text.lower():
                        stamp = line.text
                    continue
                lines.append(line)
            for group in _split_by_style(lines):
                block = _lines_to_block(group, number)
                if block is not None:
                    blocks.append(block)
        return blocks, stamp


# -------------------------------------------------------------------------- helpers


def _make_line(raw_line: dict[str, Any]) -> _Line | None:
    spans = [s for s in raw_line.get("spans", []) if s.get("text", "").strip()]
    if not spans:
        return None
    text = "".join(s["text"] for s in raw_line["spans"])
    weights = [len(s["text"].strip()) for s in spans]
    total = sum(weights) or 1
    size = sum(s["size"] * w for s, w in zip(spans, weights, strict=True)) / total
    bold_chars = sum(
        w
        for s, w in zip(spans, weights, strict=True)
        if s.get("flags", 0) & 16 or "bold" in s.get("font", "").lower()
    )
    math_chars = sum(
        w for s, w in zip(spans, weights, strict=True) if MATH_FONT_RE.search(s.get("font", ""))
    )
    return _Line(
        text=text,
        bbox=tuple(raw_line["bbox"]),  # type: ignore[arg-type]
        size=round(size, 1),
        bold=bold_chars / total > 0.6,
        math_ratio=math_chars / total,
    )


def _split_by_style(lines: list[_Line]) -> list[list[_Line]]:
    """Split a PDF block where font size/weight changes (heading + first paragraph)."""
    groups: list[list[_Line]] = []
    for line in lines:
        if groups:
            previous = groups[-1][-1]
            same_style = abs(line.size - previous.size) < 0.8 and line.bold == previous.bold
            if same_style:
                groups[-1].append(line)
                continue
        groups.append([line])
    return groups


def _union(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _lines_to_block(lines: list[_Line], page: int) -> TextBlock | None:
    raw = "\n".join(line.text for line in lines)
    if not raw.strip():
        return None
    chars = sum(len(line.text.strip()) for line in lines) or 1
    size = sum(line.size * len(line.text.strip()) for line in lines) / chars
    math_ratio = sum(line.math_ratio * len(line.text.strip()) for line in lines) / chars
    bold = sum(len(line.text.strip()) for line in lines if line.bold) / chars > 0.6
    bbox = _union([line.bbox for line in lines])

    kind = BlockKind.TEXT
    text = clean_text(raw)
    if CAPTION_RE.match(text):
        kind = BlockKind.CAPTION
    elif _looks_like_equation(text, math_ratio):
        kind = BlockKind.EQUATION
        # Keep math verbatim: only collapse whitespace, no dehyphenation/ligature edits.
        text = re.sub(r"\s+", " ", raw).strip()
    return TextBlock(
        text=text, page=page, bbox=bbox, font_size=round(size, 1), bold=bold, kind=kind
    )


def _looks_like_equation(text: str, math_font_ratio: float) -> bool:
    if len(text) > 300 or len(text) < 3:
        return False
    symbol_ratio = sum(ch in MATH_CHARS for ch in text) / len(text)
    words = re.findall(r"[A-Za-z]{4,}", text)
    numbered = bool(EQUATION_NUMBER_RE.search(text))
    if math_font_ratio > 0.5 and len(words) <= 6:
        return True
    return (symbol_ratio > 0.12 or (numbered and "=" in text)) and len(words) <= 5


def _has_visual_content(page: pymupdf.Page) -> bool:
    return bool(page.get_images(full=False)) or len(page.get_drawings()) > 20


def _find_tables(page: pymupdf.Page, number: int, has_caption: bool) -> list[RawTable]:
    found: list[RawTable] = []
    strategies: list[dict[str, str]] = [{}]
    if has_caption:  # booktabs tables: horizontal rules, columns aligned by text
        strategies.append({"vertical_strategy": "text", "horizontal_strategy": "lines"})
    for options in strategies:
        try:
            result = page.find_tables(**options)
        except Exception:
            continue
        for table in result.tables:
            rows = [[clean_text(cell or "") for cell in row] for row in table.extract()]
            rows = [row for row in rows if any(row)]
            cells = [cell for row in rows for cell in row]
            filled = sum(1 for cell in cells if cell) / max(len(cells), 1)
            # Mostly-empty grids are drawings (bar charts, boxes), not tables.
            if len(rows) >= 2 and max(len(r) for r in rows) >= 2 and filled >= 0.5:
                found.append(RawTable(page=number, rows=rows, bbox=tuple(table.bbox)))  # type: ignore[arg-type]
        if found:
            break
    return found


def _find_figures(page: pymupdf.Page, number: int) -> list[RawFigure]:
    area = page.rect.width * page.rect.height
    boxes: list[BBox] = []
    for image in page.get_image_info():
        bbox = tuple(image["bbox"])
        if (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]) > 0.02 * area:
            boxes.append(bbox)  # type: ignore[arg-type]
    try:
        for rect in page.cluster_drawings():
            if rect.width * rect.height > 0.03 * area and rect.height > 40:
                boxes.append((rect.x0, rect.y0, rect.x1, rect.y1))
    except Exception:
        pass
    return [RawFigure(page=number, bbox=b) for b in boxes]


def _overlap(a: BBox, b: BBox) -> float:
    """Intersection area as a fraction of the smaller box."""
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    smaller = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])) or 1.0
    return width * height / smaller


def _center_inside(inner: BBox, outer: BBox) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def _drop_blocks_inside(blocks: list[TextBlock], regions: list[BBox]) -> list[TextBlock]:
    if not regions:
        return blocks
    return [
        b
        for b in blocks
        if b.bbox is None
        or b.kind == BlockKind.CAPTION
        or not any(_center_inside(b.bbox, r) for r in regions)
    ]


def _reading_order(blocks: list[TextBlock], page_width: float) -> list[TextBlock]:
    """Order blocks for reading, handling two-column layouts."""
    if not blocks:
        return blocks
    mid = page_width / 2
    gutter = page_width * 0.02
    full, left, right = [], [], []
    for block in blocks:
        x0, _, x1, _ = block.bbox or (0, 0, page_width, 0)
        center = (x0 + x1) / 2
        # Full-width = actually crosses the gutter; a short heading at the start of
        # the right column sits close to the middle but is still a column block.
        if x0 < mid - gutter and x1 > mid + gutter:
            full.append(block)
        elif center < mid:
            left.append(block)
        else:
            right.append(block)

    left_chars = sum(len(b.text) for b in left)
    right_chars = sum(len(b.text) for b in right)
    total = left_chars + right_chars + sum(len(b.text) for b in full) or 1
    two_columns = left_chars / total > 0.2 and right_chars / total > 0.2
    y = lambda b: b.bbox[1] if b.bbox else 0.0  # noqa: E731
    if not two_columns:
        return sorted(blocks, key=lambda b: (round(y(b), 0), b.bbox[0] if b.bbox else 0.0))

    ordered: list[TextBlock] = []
    remaining_left = sorted(left, key=y)
    remaining_right = sorted(right, key=y)
    for separator in sorted(full, key=y):
        ordered.extend(b for b in remaining_left if y(b) < y(separator))
        ordered.extend(b for b in remaining_right if y(b) < y(separator))
        remaining_left = [b for b in remaining_left if y(b) >= y(separator)]
        remaining_right = [b for b in remaining_right if y(b) >= y(separator)]
        ordered.append(separator)
    return ordered + remaining_left + remaining_right


def _header_key(text: str) -> str:
    return re.sub(r"\d+", "#", text.lower()).strip()


def _remove_running_headers(per_page: list[list[TextBlock]], pages: list[PageInfo]) -> None:
    """Drop page numbers and text repeated in the top/bottom margin of many pages."""
    counts: Counter[str] = Counter()
    for blocks, info in zip(per_page, pages, strict=True):
        keys = {_header_key(b.text) for b in blocks if _in_margin(b, info) and len(b.text) < 150}
        counts.update(keys)
    if len(pages) < 2:
        return
    threshold = max(2, -(-len(pages) // 2))  # ceil(n/2), at least 2 pages
    repeated = {key for key, count in counts.items() if count >= threshold}
    for i, (blocks, info) in enumerate(zip(per_page, pages, strict=True)):
        per_page[i] = [
            b
            for b in blocks
            if not (
                _in_margin(b, info)
                and (_header_key(b.text) in repeated or re.fullmatch(r"[\d\s\-–/of]+", b.text))
            )
        ]


def _in_margin(block: TextBlock, info: PageInfo) -> bool:
    if block.bbox is None or not info.height:
        return False
    band = info.height * MARGIN_FRACTION
    return block.bbox[3] <= band or block.bbox[1] >= info.height - band
