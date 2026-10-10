"""Structure analysis: styled blocks → section tree with citation anchors.

Heading detection (for formats without explicit heading markup, i.e. PDF) combines:
  1. the PDF outline/bookmarks, when present (authoritative);
  2. section numbering ("3.2 Training", "IV. RESULTS") with emphasis;
  3. canonical section names ("Abstract", "References") set apart from body text;
  4. font-size statistics: body size = character-weighted mode, headings are
     emphasized short lines, levels ranked by size.
Everything before the first heading (title, authors, affiliations) becomes the
preamble, which metadata extraction consumes.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.services.ingestion.cleaning import normalize_title
from app.services.ingestion.parsers.common import CAPTION_RE
from app.services.ingestion.parsers.pdf import EQUATION_NUMBER_RE
from app.services.ingestion.types import (
    BBox,
    BlockKind,
    DocumentStructure,
    Element,
    Paragraph,
    RawDocument,
    RawFigure,
    RawTable,
    Reference,
    SectionKind,
    SectionNode,
    TextBlock,
)

_NUMBERED = re.compile(r"^(\d+(?:\.\d+){0,3})\.?\s+(\S.*)$")
_ROMAN = re.compile(r"^([IVX]{1,5})\.\s+(\S.*)$")
_LETTERED = re.compile(r"^([A-H](?:\.\d+)*)\.?\s+([A-Z].*)$")  # appendix "A.1 Proofs"
_TERMINAL = re.compile(r"[.!?:;)\]\"”]$")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+[^\s\"<>.,;])", re.I)
_ARXIV_RE = re.compile(r"arxiv[:\s/]*(?:abs/)?(\d{4}\.\d{4,5})(v\d+)?", re.I)
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)[a-z]?\b")

# Ordered: first match wins, so specific phrases come before generic words.
_SECTION_PATTERNS: list[tuple[SectionKind, re.Pattern[str]]] = [
    (SectionKind.ABSTRACT, re.compile(r"^abstract\b")),
    (SectionKind.ACKNOWLEDGMENTS, re.compile(r"^acknowledge?ments?\b")),
    (
        SectionKind.REFERENCES,
        re.compile(r"^(references|bibliography|works cited|literature cited)\b"),
    ),
    (SectionKind.APPENDIX, re.compile(r"^(appendix|appendices|supplementary)")),
    (SectionKind.FUTURE_WORK, re.compile(r"future (work|directions|research)")),
    (SectionKind.LIMITATIONS, re.compile(r"limitation|threats to validity|broader impact|ethic")),
    (
        SectionKind.RELATED_WORK,
        re.compile(r"related work|background|prior work|literature review|preliminar"),
    ),
    (SectionKind.INTRODUCTION, re.compile(r"^introduction|^overview|^motivation")),
    (SectionKind.CONCLUSION, re.compile(r"conclu|summary|closing remarks")),
    (SectionKind.DISCUSSION, re.compile(r"discussion")),
    (SectionKind.RESULTS, re.compile(r"results?\b|findings|analysis|ablation")),
    (
        SectionKind.EXPERIMENTS,
        re.compile(r"experiment|evaluation|setup|implementation|benchmark|dataset"),
    ),
    (
        SectionKind.METHOD,
        re.compile(
            r"method|approach|model|framework|architecture|proposed|algorithm|design|formulation|training"
        ),
    ),
]
_CANONICAL_NAMES = {
    "abstract", "introduction", "related work", "background", "method", "methods",
    "methodology", "approach", "experiments", "experimental setup", "results",
    "discussion", "limitations", "conclusion", "conclusions", "references",
    "bibliography", "acknowledgments", "acknowledgements", "appendix", "future work",
    "evaluation", "preliminaries", "analysis",
}  # fmt: skip


_NUMBER_PREFIX = re.compile(r"^(?:\d+(?:\.\d+)*\.?|[IVX]{1,5}\.|[A-H](?:\.\d+)*\.?)\s+")


def _strip_number(title: str) -> str:
    """'3.2 Training' -> 'Training', 'IV. RESULTS' -> 'RESULTS' (never eats 'Introduction')."""
    return _NUMBER_PREFIX.sub("", title.strip())


def classify_section(title: str) -> SectionKind:
    normalized = _strip_number(title).lower()
    for kind, pattern in _SECTION_PATTERNS:
        if pattern.search(normalized):
            return kind
    return SectionKind.OTHER


@dataclass(slots=True)
class _Heading:
    block: TextBlock
    level: int
    number: str | None
    title: str


class HeadingDetector:
    def __init__(self, raw: RawDocument) -> None:
        self.raw = raw
        text_blocks = [b for b in raw.blocks if b.kind == BlockKind.TEXT and b.font_size]
        sizes: Counter[float] = Counter()
        for block in text_blocks:
            sizes[round((block.font_size or 0) * 2) / 2] += len(block.text)
        self.body_size = sizes.most_common(1)[0][0] if sizes else 10.0
        self.outline = [
            (entry["level"], normalize_title(str(entry["title"])), int(entry["page"]))
            for entry in raw.outline
            if entry.get("title")
        ]
        self.trust_outline = len(self.outline) >= 3
        self.title_block = self._find_title_block()

    def _find_title_block(self) -> TextBlock | None:
        candidates = [
            b
            for b in self.raw.blocks
            if b.page == 1 and b.font_size and b.kind == BlockKind.TEXT and len(b.text) > 8
        ]
        if not candidates:
            return None
        biggest = max(candidates, key=lambda b: b.font_size or 0)
        return biggest if (biggest.font_size or 0) >= self.body_size + 2 else None

    def detect(self) -> dict[int, _Heading]:
        """Return {block index: heading} for blocks that are section headings."""
        found: dict[int, _Heading] = {}
        size_based: list[tuple[int, TextBlock]] = []
        preamble = True
        title_index = self.explicit_title_index()
        # Markup levels are relative: in Markdown with a `# Title`, `##` is a top-level section.
        used = sorted(
            {
                b.heading_level
                for i, b in enumerate(self.raw.blocks)
                if b.kind == BlockKind.HEADING and b.heading_level and i != title_index
            }
        )
        explicit_levels = {level: rank + 1 for rank, level in enumerate(used)}
        for index, block in enumerate(self.raw.blocks):
            if block is self.title_block or index == title_index:
                continue
            if block.kind == BlockKind.HEADING and block.heading_level is not None:
                if block.heading_level == 0:  # document title style
                    continue
                found[index] = self._make(block, explicit_levels[block.heading_level])
                preamble = False
                continue
            if block.kind != BlockKind.TEXT or not self._heading_shaped(block.text):
                continue
            heading = self._classify(block, allow_style_only=not preamble)
            if heading == "size":
                size_based.append((index, block))
                preamble = False
            elif heading is not None:
                found[index] = heading
                preamble = False
        # Rank unnumbered, style-only headings by font size (largest → level 1).
        distinct = sorted({round(b.font_size or 0, 0) for _, b in size_based}, reverse=True)
        for index, block in size_based:
            level = distinct.index(round(block.font_size or 0, 0)) + 1
            found[index] = self._make(block, min(level, 3))
        return found

    def explicit_title_index(self) -> int | None:
        """A lone top-level first heading (Markdown `# Title`, HTML <h1>) is the title."""
        explicit = [
            (i, b.heading_level)
            for i, b in enumerate(self.raw.blocks)
            if b.kind == BlockKind.HEADING and b.heading_level is not None
        ]
        if len(explicit) < 2:
            return None
        first_index, first_level = explicit[0]
        if all(level > first_level for _, level in explicit[1:]):
            return first_index
        return None

    def _heading_shaped(self, text: str) -> bool:
        words = text.split()
        if not 0 < len(words) <= 14 or len(text) > 120:
            return False
        return not text.endswith((".", ",", ";")) or bool(_NUMBERED.match(text))

    def _emphasized(self, block: TextBlock) -> bool:
        size = block.font_size or self.body_size
        return block.bold or size >= self.body_size + 0.8 or block.text.isupper()

    def _classify(self, block: TextBlock, allow_style_only: bool) -> _Heading | str | None:
        text = block.text.strip()
        normalized = normalize_title(text)
        if self.outline:
            for level, title, page in self.outline:
                if (
                    abs(page - block.page) <= 1
                    and title
                    and (normalized == title or (len(title) > 8 and normalized.startswith(title)))
                ):
                    return self._make(block, level)
            if self.trust_outline:
                # Outline is authoritative; only accept canonical names beyond it.
                return self._make(block, 1) if self._canonical(block) else None

        m = _NUMBERED.match(text)
        if (
            m
            and self._emphasized(block)
            and m.group(2)[:1].isupper()
            and len(m.group(2)) > 2
            and not re.fullmatch(r"[\d.\s]+", m.group(2))
        ):
            return self._make(block, m.group(1).count(".") + 1)
        if (m := _ROMAN.match(text)) and self._emphasized(block):
            return self._make(block, 1)
        if self._canonical(block):
            return self._make(block, 1)
        if (m := _LETTERED.match(text)) and block.bold and allow_style_only:
            return self._make(block, m.group(1).count(".") + 1)
        if allow_style_only and self._emphasized(block) and len(text.split()) <= 10:
            size = block.font_size or self.body_size
            if size >= self.body_size + 1.2 or (block.bold and text[:1].isupper()):
                return "size"
        return None

    def _canonical(self, block: TextBlock) -> bool:
        name = _strip_number(block.text).lower().rstrip(":")
        return name in _CANONICAL_NAMES and (self._emphasized(block) or not block.font_size)

    def _make(self, block: TextBlock, level: int) -> _Heading:
        text = block.text.strip()
        number = None
        for pattern in (_NUMBERED, _ROMAN):
            if m := pattern.match(text):
                number, text = m.group(1), m.group(2)
                break
        return _Heading(block=block, level=max(1, level), number=number, title=text.rstrip(":"))


class StructureBuilder:
    def __init__(self, raw: RawDocument) -> None:
        self.raw = raw
        self.parts: list[str] = []
        self.offset = 0
        self.page_spans: dict[int, list[int]] = {}

    # --- text assembly with offsets ------------------------------------------------

    def _append(self, text: str, page_start: int, page_end: int) -> tuple[int, int]:
        if self.parts:
            self.parts.append("\n\n")
            self.offset += 2
        start = self.offset
        self.parts.append(text)
        self.offset += len(text)
        for page, value in ((page_start, start), (page_end, self.offset)):
            span = self.page_spans.setdefault(page, [value, value])
            span[0], span[1] = min(span[0], value), max(span[1], value)
        return start, self.offset

    # --- build ---------------------------------------------------------------------------

    def build(self) -> DocumentStructure:
        detector = HeadingDetector(self.raw)
        headings = detector.detect()

        preamble = SectionNode(title="", level=0, kind=SectionKind.PREAMBLE)
        roots: list[SectionNode] = []
        stack: list[SectionNode] = []
        current = preamble

        for item in _merge_continuations(self.raw.blocks, headings):
            block, heading = item.block, item.heading
            if heading is not None:
                kind = classify_section(heading.title)
                while stack and stack[-1].level >= heading.level:
                    stack.pop()
                if kind == SectionKind.OTHER and stack:
                    kind = stack[-1].kind  # "3.2 Loss function" inherits "method"
                start, end = self._append(heading.block.text.strip(), block.page, block.page)
                node = SectionNode(
                    title=heading.title,
                    level=heading.level,
                    kind=kind,
                    number=heading.number,
                    page_start=block.page,
                    page_end=block.page,
                    char_start=start,
                    char_end=end,
                )
                (stack[-1].children if stack else roots).append(node)
                stack.append(node)
                current = node
                continue
            page_end = item.page_end
            start, end = self._append(item.text, block.page, page_end)
            current.paragraphs.append(
                Paragraph(
                    text=item.text,
                    kind=block.kind,
                    page_start=block.page,
                    page_end=page_end,
                    char_start=start,
                    char_end=end,
                    boxes=item.boxes,
                )
            )
            for node in stack:  # extend every open ancestor
                node.page_end = max(node.page_end, page_end)
                node.char_end = end

        sections = ([preamble] if preamble.paragraphs else []) + roots
        if preamble.paragraphs:
            preamble.page_start = preamble.paragraphs[0].page_start
            preamble.page_end = preamble.paragraphs[-1].page_end
            preamble.char_start = preamble.paragraphs[0].char_start
            preamble.char_end = preamble.paragraphs[-1].char_end

        structure = DocumentStructure(
            full_text="".join(self.parts),
            page_spans=self._final_page_spans(),
            sections=sections,
        )
        structure.elements = build_elements(structure, self.raw.tables, self.raw.figures)
        structure.references = extract_references(structure)
        return structure

    def _final_page_spans(self) -> dict[int, tuple[int, int]]:
        spans: dict[int, tuple[int, int]] = {}
        previous_end = 0
        for page in self.raw.pages:
            if page.number in self.page_spans:
                start, end = self.page_spans[page.number]
                spans[page.number] = (start, end)
                previous_end = end
            else:
                spans[page.number] = (previous_end, previous_end)
        return spans


def _boxes(block: TextBlock) -> list[tuple[int, float, float, float, float]]:
    return [(block.page, *block.bbox)] if block.bbox else []


@dataclass(slots=True)
class _Item:
    """A block in reading order, possibly merged across a column/page break."""

    block: TextBlock
    heading: _Heading | None
    text: str
    page_end: int
    boxes: list[tuple[int, float, float, float, float]]


def _merge_continuations(blocks: list[TextBlock], headings: dict[int, _Heading]) -> list[_Item]:
    """Join paragraphs split by a column or page break ("...the model" | "is trained...")."""
    items: list[_Item] = []
    for index, block in enumerate(blocks):
        heading = headings.get(index)
        if heading is None and items:
            previous = items[-1]
            if (
                previous.heading is None
                and previous.block.kind == block.kind == BlockKind.TEXT
                and previous.block.bold == block.bold
                and abs((previous.block.font_size or 0) - (block.font_size or 0)) < 0.8
                and not _TERMINAL.search(previous.text)
                and block.text[:1].islower()
                and block.page - previous.page_end <= 1
            ):
                previous.text = f"{previous.text} {block.text}"
                previous.page_end = block.page
                previous.boxes.extend(_boxes(block))
                continue
        items.append(_Item(block, heading, block.text, block.page, _boxes(block)))
    return items


# --- elements ------------------------------------------------------------------------------


def _vertical_gap(a: BBox, b: BBox) -> float:
    if a[3] < b[1]:
        return b[1] - a[3]
    if b[3] < a[1]:
        return a[1] - b[3]
    return 0.0


def _nearest(caption_box: BBox | None, candidates: list[BBox]) -> BBox | None:
    if caption_box is None or not candidates:
        return None
    best = min(candidates, key=lambda box: _vertical_gap(caption_box, box))
    return best if _vertical_gap(caption_box, best) < 120 else None


def build_elements(
    structure: DocumentStructure, tables: list[RawTable], figures: list[RawFigure]
) -> list[Element]:
    paragraphs = [p for s in structure.all_sections() for p in s.paragraphs]
    text_paragraphs = [p for p in paragraphs if p.kind == BlockKind.TEXT]
    elements: list[Element] = []
    used_tables: set[int] = set()

    for position, paragraph in enumerate(paragraphs):
        if paragraph.kind == BlockKind.CAPTION:
            match = CAPTION_RE.match(paragraph.text)
            if not match:
                continue
            word = match.group(1).lower()
            kind = (
                "table"
                if word.startswith("table")
                else "algorithm"
                if word.startswith("algo")
                else "figure"
            )
            number = match.group(2)
            label = f"{kind.capitalize()} {number}"
            caption_box = tuple(paragraph.boxes[0][1:]) if paragraph.boxes else None
            element = Element(
                kind="table" if kind == "table" else "figure",
                page=paragraph.page_start,
                label=label,
                number=number,
                caption=paragraph.text,
            )
            if kind == "table":
                page_tables = [
                    (i, t)
                    for i, t in enumerate(tables)
                    if t.page == paragraph.page_start and i not in used_tables
                ]
                box = _nearest(caption_box, [t.bbox for _, t in page_tables if t.bbox])  # type: ignore[arg-type]
                chosen = (
                    next((it for it in page_tables if it[1].bbox == box), None) if box else None
                )
                if chosen is None and len(page_tables) == 1:
                    # Caption and table split across a column break: still unambiguous.
                    chosen = page_tables[0]
                if chosen:
                    used_tables.add(chosen[0])
                    element.bbox = chosen[1].bbox
                    element.content = {"rows": chosen[1].rows}
            else:
                page_figures = [
                    f.bbox for f in figures if f.page == paragraph.page_start and f.bbox
                ]
                element.bbox = _nearest(caption_box, page_figures)  # type: ignore[arg-type]
            element.context = _mentions(text_paragraphs, label)
            elements.append(element)
        elif paragraph.kind == BlockKind.EQUATION:
            number_match = EQUATION_NUMBER_RE.search(paragraph.text)
            number = number_match.group(1) if number_match else None
            before = paragraphs[position - 1].text if position > 0 else ""
            after = paragraphs[position + 1].text if position + 1 < len(paragraphs) else ""
            elements.append(
                Element(
                    kind="equation",
                    page=paragraph.page_start,
                    label=f"Equation {number}" if number else None,
                    number=number,
                    bbox=tuple(paragraph.boxes[0][1:]) if paragraph.boxes else None,  # type: ignore[arg-type]
                    content={"text": paragraph.text},
                    context=" … ".join(t for t in (before[-600:], after[:600]) if t) or None,
                )
            )

    for index, table in enumerate(tables):  # uncaptioned tables are still tables
        if (
            index not in used_tables
            and table.caption is None
            and not any(e.kind == "table" and e.content.get("rows") == table.rows for e in elements)
        ):
            elements.append(
                Element(
                    kind="table", page=table.page, bbox=table.bbox, content={"rows": table.rows}
                )
            )
        elif table.caption and not any(e.caption == table.caption for e in elements):
            elements.append(
                Element(
                    kind="table",
                    page=table.page,
                    caption=table.caption,
                    content={"rows": table.rows},
                )
            )
    return elements


def _mentions(paragraphs: list[Paragraph], label: str) -> str | None:
    kind, number = label.split(" ", 1)
    pattern = re.compile(rf"\b({kind}|{kind[:3]}\.)\s*{re.escape(number)}\b", re.I)
    hits = [p.text for p in paragraphs if pattern.search(p.text)][:2]
    return " … ".join(h[:600] for h in hits) or None


# --- references ----------------------------------------------------------------------------


def extract_references(structure: DocumentStructure) -> list[Reference]:
    sections = [s for s in structure.all_sections() if s.kind == SectionKind.REFERENCES]
    raw_entries: list[str] = []
    for section in sections:
        for paragraph in section.paragraphs:
            parts = re.split(r"(?=\[\d{1,3}\]\s)", paragraph.text)
            raw_entries.extend(p.strip() for p in parts if len(p.strip()) > 15)
    references: list[Reference] = []
    for index, entry in enumerate(raw_entries, start=1):
        doi = _DOI_RE.search(entry)
        arxiv = _ARXIV_RE.search(entry)
        years = [int(y) for y in _YEAR_RE.findall(entry)]
        references.append(
            Reference(
                index=index,
                raw_text=entry[:2000],
                title=_guess_reference_title(entry),
                year=years[0] if years else None,
                doi=doi.group(1) if doi else None,
                arxiv_id=arxiv.group(1) if arxiv else None,
            )
        )
    return references


def _guess_reference_title(entry: str) -> str | None:
    """Authors. (Year.) Title. Venue — the title is usually the 2nd sentence-like segment."""
    text = re.sub(r"^\[\d+\]\s*", "", entry)
    quoted = re.search(r"[“\"](.{10,300}?)[”\"]", text)
    if quoted:
        return quoted.group(1).strip(" ,.")
    segments = [
        s.strip() for s in re.split(r"(?<!\b[A-Z])\.\s+(?=[A-Z0-9“\"(])", text) if s.strip()
    ]
    for segment in segments[1:]:
        if re.fullmatch(r"\(?\d{4}[a-z]?\)?", segment):
            continue
        if len(segment.split()) >= 3:
            segment = re.split(r"[.,]\s+(?:arXiv|In|Proceedings|doi)", segment)[0]
            return segment.strip(" ,.")[:300]
    return None


def build_structure(raw: RawDocument) -> DocumentStructure:
    return StructureBuilder(raw).build()
