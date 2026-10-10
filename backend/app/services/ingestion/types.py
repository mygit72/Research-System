"""Intermediate representations for the ingestion pipeline.

    file ──parser──▶ RawDocument ──structure──▶ DocumentStructure ──metadata──▶ ExtractedMetadata

`RawDocument` is format-specific output normalized into styled text blocks in
reading order. `DocumentStructure` is format-agnostic: a section tree whose
paragraphs carry page numbers, character offsets into `full_text` and PDF
bounding boxes — the anchors citations point back to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

BBox = tuple[float, float, float, float]


class DocumentFormat(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"


class BlockKind(StrEnum):
    TEXT = "text"
    HEADING = "heading"
    LIST_ITEM = "list_item"
    CODE = "code"
    EQUATION = "equation"
    CAPTION = "caption"
    TABLE = "table"  # rendered as a Markdown table so it stays retrievable


class SectionKind(StrEnum):
    PREAMBLE = "preamble"  # title/authors block before the first heading
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    RELATED_WORK = "related_work"
    METHOD = "method"
    EXPERIMENTS = "experiments"
    RESULTS = "results"
    DISCUSSION = "discussion"
    LIMITATIONS = "limitations"
    CONCLUSION = "conclusion"
    FUTURE_WORK = "future_work"
    REFERENCES = "references"
    ACKNOWLEDGMENTS = "acknowledgments"
    APPENDIX = "appendix"
    OTHER = "other"


# --- Parser output -----------------------------------------------------------------


@dataclass(slots=True)
class TextBlock:
    text: str
    page: int  # 1-based
    bbox: BBox | None = None
    font_size: float | None = None
    bold: bool = False
    kind: BlockKind = BlockKind.TEXT
    # Known when the format encodes it (DOCX styles, HTML <h2>, Markdown ##).
    heading_level: int | None = None


@dataclass(slots=True)
class RawTable:
    page: int
    rows: list[list[str]]
    bbox: BBox | None = None
    caption: str | None = None


@dataclass(slots=True)
class RawFigure:
    page: int
    bbox: BBox | None = None
    caption: str | None = None


@dataclass(slots=True)
class PageInfo:
    number: int
    width: float | None = None
    height: float | None = None
    used_ocr: bool = False


@dataclass
class RawDocument:
    format: DocumentFormat
    pages: list[PageInfo]
    blocks: list[TextBlock]
    tables: list[RawTable] = field(default_factory=list)
    figures: list[RawFigure] = field(default_factory=list)
    embedded_metadata: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    paginated: bool = True
    parser: str = ""
    # Authoritative headings when the file has them (PDF bookmarks): level/title/page.
    outline: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ocr_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.used_ocr]


# --- Structure --------------------------------------------------------------------


@dataclass(slots=True)
class Paragraph:
    text: str
    kind: BlockKind
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    # (page, x0, y0, x1, y1) rectangles for highlighting in the reader (PDF only).
    boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "kind": self.kind.value,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "boxes": [list(b) for b in self.boxes],
        }


@dataclass
class SectionNode:
    title: str
    level: int
    kind: SectionKind
    number: str | None = None
    page_start: int = 1
    page_end: int = 1
    char_start: int = 0
    char_end: int = 0
    paragraphs: list[Paragraph] = field(default_factory=list)
    children: list[SectionNode] = field(default_factory=list)

    def walk(self) -> list[SectionNode]:
        nodes = [self]
        for child in self.children:
            nodes.extend(child.walk())
        return nodes


@dataclass(slots=True)
class Element:
    """A figure, table or equation, located on a page."""

    kind: str  # "figure" | "table" | "equation"
    page: int
    label: str | None = None  # "Figure 3", "Table 2", "Equation 4"
    number: str | None = None
    caption: str | None = None
    bbox: BBox | None = None
    content: dict[str, Any] = field(default_factory=dict)
    context: str | None = None  # nearby explanatory text


@dataclass(slots=True)
class Reference:
    index: int
    raw_text: str
    title: str | None = None
    year: int | None = None
    doi: str | None = None
    arxiv_id: str | None = None


@dataclass
class DocumentStructure:
    full_text: str
    page_spans: dict[int, tuple[int, int]]  # page -> (char_start, char_end)
    sections: list[SectionNode]  # top-level; preamble first when present
    elements: list[Element] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)

    def all_sections(self) -> list[SectionNode]:
        return [node for top in self.sections for node in top.walk()]


# --- Metadata --------------------------------------------------------------------------


@dataclass
class ExtractedMetadata:
    title: str | None = None
    authors: list[dict[str, str | None]] = field(default_factory=list)
    affiliations: list[str] = field(default_factory=list)
    abstract: str | None = None
    year: int | None = None
    publication_date: str | None = None
    venue: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    keywords: list[str] = field(default_factory=list)
    research_area: str | None = None
    # field -> {"source": ..., "confidence": "high" | "medium" | "low"}
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)
