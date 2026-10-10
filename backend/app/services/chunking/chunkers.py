"""Chunking strategies.

All strategies emit `ChunkDraft`s whose `text` is (except for split tables) the
exact slice `full_text[char_start:char_end]`, so every retrieved passage can be
traced back to a page, section and highlight box.

| strategy       | respects sections | respects sentences | notes                              |
|----------------|-------------------|--------------------|------------------------------------|
| fixed          | no                | no                 | token windows with overlap          |
| recursive      | no                | partly             | split on \\n\\n, \\n, ". ", " "        |
| sentence       | no                | yes                | pack sentences, sentence overlap    |
| section_aware  | yes               | yes                | default; tables/equations atomic    |
| semantic       | yes               | yes                | split where adjacent-sentence       |
|                |                   |                    | embedding similarity drops         |
"""

from __future__ import annotations

import bisect
import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from app.services.chunking.sentences import sentence_spans
from app.services.chunking.tokens import TokenCounter

ATOMIC_KINDS = {"table", "equation", "caption", "code"}
EmbedFn = Callable[[list[str]], np.ndarray]


class ChunkingStrategy(StrEnum):
    FIXED = "fixed"
    RECURSIVE = "recursive"
    SENTENCE = "sentence"
    SECTION_AWARE = "section_aware"
    SEMANTIC = "semantic"


@dataclass(slots=True)
class SourceParagraph:
    text: str
    kind: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    boxes: list[list[float]] = field(default_factory=list)


@dataclass(slots=True)
class SourceSection:
    key: str  # stable id of the stored section
    title: str
    path: list[str]  # e.g. ["3 Method", "3.1 Training Objective"]
    kind: str
    paragraphs: list[SourceParagraph]

    @property
    def char_start(self) -> int:
        return self.paragraphs[0].char_start if self.paragraphs else 0

    @property
    def char_end(self) -> int:
        return self.paragraphs[-1].char_end if self.paragraphs else 0


@dataclass
class ChunkSource:
    document_title: str
    full_text: str
    sections: list[SourceSection]
    page_spans: dict[int, tuple[int, int]]


@dataclass(slots=True)
class ChunkDraft:
    text: str
    char_start: int
    char_end: int
    page_start: int
    page_end: int
    section_key: str | None
    section_title: str
    section_path: list[str]
    section_kind: str
    paragraph_index: int
    kind: str
    token_count: int
    boxes: list[list[float]] = field(default_factory=list)
    context_header: str = ""

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()

    @property
    def embedding_text(self) -> str:
        """What gets embedded: optional "Paper › Section" header + the passage."""
        return f"{self.context_header}\n\n{self.text}" if self.context_header else self.text


@dataclass(frozen=True, slots=True)
class ChunkingConfig:
    strategy: ChunkingStrategy = ChunkingStrategy.SECTION_AWARE
    chunk_size: int = 384  # tokens
    chunk_overlap: int = 64  # tokens (sentence-based strategies convert to whole sentences)
    contextual_headers: bool = True
    semantic_percentile: float = 85.0  # distance percentile that triggers a split


class _Locator:
    """Map a global character offset to its page and section."""

    def __init__(self, source: ChunkSource) -> None:
        self.page_starts = sorted((span[0], page) for page, span in source.page_spans.items())
        self.sections = [s for s in source.sections if s.paragraphs]
        self.section_starts = [s.char_start for s in self.sections]

    def page(self, offset: int) -> int:
        index = bisect.bisect_right([start for start, _ in self.page_starts], offset) - 1
        return self.page_starts[max(index, 0)][1] if self.page_starts else 1

    def section(self, offset: int) -> SourceSection | None:
        index = bisect.bisect_right(self.section_starts, offset) - 1
        return self.sections[index] if index >= 0 and self.sections else None


def _boxes_between(section: SourceSection | None, start: int, end: int) -> list[list[float]]:
    if section is None:
        return []
    return [
        box
        for p in section.paragraphs
        if p.char_start < end and p.char_end > start
        for box in p.boxes
    ]


class Chunker:
    def __init__(
        self, config: ChunkingConfig, counter: TokenCounter, embed: EmbedFn | None = None
    ) -> None:
        if config.chunk_overlap >= config.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if config.strategy == ChunkingStrategy.SEMANTIC and embed is None:
            raise ValueError("semantic chunking needs an embedding function")
        self.config = config
        self.counter = counter
        self.embed = embed

    # --- public ------------------------------------------------------------------------

    def chunk(self, source: ChunkSource) -> list[ChunkDraft]:
        handler = {
            ChunkingStrategy.FIXED: self._fixed,
            ChunkingStrategy.RECURSIVE: self._recursive,
            ChunkingStrategy.SENTENCE: self._sentence,
            ChunkingStrategy.SECTION_AWARE: self._section_aware,
            ChunkingStrategy.SEMANTIC: self._semantic,
        }[self.config.strategy]
        drafts = [d for d in handler(source) if d.text.strip()]
        if self.config.contextual_headers:
            for draft in drafts:
                path = " › ".join(p for p in draft.section_path if p)
                draft.context_header = " › ".join(x for x in (source.document_title, path) if x)
        return drafts

    # --- helpers -----------------------------------------------------------------------

    def _draft_from_span(
        self, source: ChunkSource, locator: _Locator, start: int, end: int
    ) -> ChunkDraft:
        text = source.full_text[start:end]
        section = locator.section(start)
        paragraph_index = 0
        kind = "text"
        if section is not None:
            for index, p in enumerate(section.paragraphs):
                if p.char_end > start:
                    paragraph_index = index
                    kind = p.kind if p.kind in ATOMIC_KINDS and p.char_end >= end else "text"
                    break
        return ChunkDraft(
            text=text,
            char_start=start,
            char_end=end,
            page_start=locator.page(start),
            page_end=locator.page(max(start, end - 1)),
            section_key=section.key if section else None,
            section_title=section.title if section else "",
            section_path=section.path if section else [],
            section_kind=section.kind if section else "other",
            paragraph_index=paragraph_index,
            kind=kind,
            token_count=self.counter.count(text),
            boxes=_boxes_between(section, start, end),
        )

    def _pack(
        self,
        units: list[tuple[int, int]],
        full_text: str,
        overlap_tokens: int,
    ) -> list[tuple[int, int]]:
        """Greedily pack consecutive spans up to chunk_size tokens, with token overlap."""
        size = self.config.chunk_size
        costs = [self.counter.count(full_text[s:e]) for s, e in units]
        windows: list[tuple[int, int]] = []
        i = 0
        while i < len(units):
            total, j = 0, i
            while j < len(units) and (total + costs[j] <= size or j == i):
                total += costs[j]
                j += 1
            windows.append((units[i][0], units[j - 1][1]))
            if j >= len(units):
                break
            # Step back over trailing units that fit in the overlap budget.
            back, carried = j, 0
            while back - 1 > i and carried + costs[back - 1] <= overlap_tokens:
                back -= 1
                carried += costs[back]
            i = back
        return windows

    # --- strategies ------------------------------------------------------------------------

    def _fixed(self, source: ChunkSource) -> list[ChunkDraft]:
        locator = _Locator(source)
        spans = self.counter.spans(source.full_text)
        size, step = self.config.chunk_size, self.config.chunk_size - self.config.chunk_overlap
        drafts = []
        for first in range(0, len(spans), step):
            window = spans[first : first + size]
            drafts.append(self._draft_from_span(source, locator, window[0][0], window[-1][1]))
            if first + size >= len(spans):
                break
        return drafts

    def _recursive(self, source: ChunkSource) -> list[ChunkDraft]:
        locator = _Locator(source)
        text = source.full_text
        separators = ["\n\n", "\n", ". ", " "]

        def split(start: int, end: int, level: int) -> list[tuple[int, int]]:
            if self.counter.count(text[start:end]) <= self.config.chunk_size or level >= len(
                separators
            ):
                return [(start, end)]
            separator = separators[level]
            pieces: list[tuple[int, int]] = []
            cursor = start
            while cursor < end:
                found = text.find(separator, cursor, end)
                stop = end if found == -1 else found + len(separator)
                pieces.extend(split(cursor, stop, level + 1))
                cursor = stop
            return pieces

        units = [(s, e) for s, e in split(0, len(text), 0) if text[s:e].strip()]
        windows = self._pack(units, text, self.config.chunk_overlap)
        return [self._draft_from_span(source, locator, *_trim(text, s, e)) for s, e in windows]

    def _sentence(self, source: ChunkSource) -> list[ChunkDraft]:
        locator = _Locator(source)
        units: list[tuple[int, int]] = []
        for section in source.sections:
            for p in section.paragraphs:
                units.extend(sentence_spans(p.text, p.char_start) or [(p.char_start, p.char_end)])
        windows = self._pack(units, source.full_text, self.config.chunk_overlap)
        return [self._draft_from_span(source, locator, s, e) for s, e in windows]

    def _section_units(self, section: SourceSection) -> list[tuple[int, int, bool]]:
        """(start, end, atomic) units: whole paragraphs, or sentences of long ones."""
        units: list[tuple[int, int, bool]] = []
        for p in section.paragraphs:
            if p.kind in ATOMIC_KINDS:
                units.append((p.char_start, p.char_end, True))
            elif self.counter.count(p.text) <= self.config.chunk_size:
                units.append((p.char_start, p.char_end, False))
            else:
                for s, e in sentence_spans(p.text, p.char_start):
                    units.append((s, e, False))
        return units

    def _section_aware(self, source: ChunkSource) -> list[ChunkDraft]:
        locator = _Locator(source)
        drafts: list[ChunkDraft] = []
        for section in source.sections:
            if not section.paragraphs:
                continue
            units = self._section_units(section)
            buffer: list[tuple[int, int]] = []

            def flush(buffer: list[tuple[int, int]] = buffer) -> None:
                if buffer:
                    windows = self._pack(buffer, source.full_text, self.config.chunk_overlap)
                    drafts.extend(self._draft_from_span(source, locator, s, e) for s, e in windows)
                    buffer.clear()

            for start, end, atomic in units:
                if atomic:  # tables / equations / captions stand alone
                    flush()
                    drafts.extend(self._atomic(source, locator, start, end))
                else:
                    buffer.append((start, end))
            flush()
        return drafts

    def _atomic(
        self, source: ChunkSource, locator: _Locator, start: int, end: int
    ) -> list[ChunkDraft]:
        draft = self._draft_from_span(source, locator, start, end)
        if draft.token_count <= self.config.chunk_size or draft.kind != "table":
            return [draft]
        # Oversized table: split by rows, repeating the header so each part is readable.
        lines = draft.text.split("\n")
        header, rows = lines[:2], lines[2:]
        parts: list[ChunkDraft] = []
        current: list[str] = []
        for row in rows:
            candidate = "\n".join(header + current + [row])
            if current and self.counter.count(candidate) > self.config.chunk_size:
                parts.append(self._table_part(draft, header + current))
                current = []
            current.append(row)
        if current:
            parts.append(self._table_part(draft, header + current))
        return parts

    def _table_part(self, base: ChunkDraft, lines: list[str]) -> ChunkDraft:
        text = "\n".join(lines)
        return ChunkDraft(
            text=text,
            char_start=base.char_start,
            char_end=base.char_end,
            page_start=base.page_start,
            page_end=base.page_end,
            section_key=base.section_key,
            section_title=base.section_title,
            section_path=base.section_path,
            section_kind=base.section_kind,
            paragraph_index=base.paragraph_index,
            kind="table",
            token_count=self.counter.count(text),
            boxes=base.boxes,
        )

    def _semantic(self, source: ChunkSource) -> list[ChunkDraft]:
        assert self.embed is not None
        locator = _Locator(source)
        drafts: list[ChunkDraft] = []
        for section in source.sections:
            units = self._section_units(section)
            text_units = [(s, e) for s, e, atomic in units if not atomic]
            for s, e, atomic in units:
                if atomic:
                    drafts.extend(self._atomic(source, locator, s, e))
            if not text_units:
                continue
            # Sentence-level units give the similarity signal finer resolution.
            sentences: list[tuple[int, int]] = []
            for s, e in text_units:
                sentences.extend(sentence_spans(source.full_text[s:e], s) or [(s, e)])
            breaks = self._semantic_breaks(source.full_text, sentences)
            group: list[tuple[int, int]] = []
            for index, span in enumerate(sentences):
                if index in breaks and group:
                    drafts.extend(
                        self._draft_from_span(source, locator, gs, ge)
                        for gs, ge in self._pack(group, source.full_text, 0)
                    )
                    group = []
                group.append(span)
            if group:
                drafts.extend(
                    self._draft_from_span(source, locator, gs, ge)
                    for gs, ge in self._pack(group, source.full_text, 0)
                )
        drafts.sort(key=lambda d: d.char_start)
        return drafts

    def _semantic_breaks(self, text: str, sentences: list[tuple[int, int]]) -> set[int]:
        if len(sentences) < 3:
            return set()
        assert self.embed is not None
        vectors = self.embed([text[s:e] for s, e in sentences])
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        vectors = vectors / np.clip(norms, 1e-9, None)
        distances = 1.0 - np.sum(vectors[:-1] * vectors[1:], axis=1)
        threshold = float(np.percentile(distances, self.config.semantic_percentile))
        return {i + 1 for i, d in enumerate(distances) if d >= threshold and d > 0}


def _trim(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end
