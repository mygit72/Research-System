"""Structure-aware chunking (see chunkers.py for the strategies)."""

from __future__ import annotations

from typing import Any

from app.services.chunking.chunkers import (
    ChunkDraft,
    Chunker,
    ChunkingConfig,
    ChunkingStrategy,
    ChunkSource,
    SourceParagraph,
    SourceSection,
)
from app.services.chunking.tokens import TokenCounter, get_token_counter


def _label(number: str | None, title: str) -> str:
    return f"{number} {title}".strip() if number else title


def source_from_sections(
    document_title: str,
    full_text: str,
    page_spans: dict[int, tuple[int, int]],
    sections: list[Any],
) -> ChunkSource:
    """Build a ChunkSource from stored `Section` rows (ordered by position).

    Works with any objects exposing id, parent_id, title, number, kind, paragraphs.
    """
    by_id = {str(s.id): s for s in sections}

    def path(section: Any) -> list[str]:
        labels = []
        node = section
        while node is not None:
            if node.kind != "preamble":
                labels.append(_label(node.number, node.title))
            node = by_id.get(str(node.parent_id)) if node.parent_id else None
        return list(reversed(labels))

    return ChunkSource(
        document_title=document_title,
        full_text=full_text,
        page_spans=page_spans,
        sections=[
            SourceSection(
                key=str(s.id),
                title=s.title,
                path=path(s),
                kind=s.kind,
                paragraphs=[SourceParagraph(**p) for p in s.paragraphs],
            )
            for s in sections
        ],
    )


__all__ = [
    "ChunkDraft",
    "ChunkSource",
    "Chunker",
    "ChunkingConfig",
    "ChunkingStrategy",
    "TokenCounter",
    "get_token_counter",
    "source_from_sections",
]
