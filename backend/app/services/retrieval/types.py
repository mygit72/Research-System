from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class SearchMode(StrEnum):
    KEYWORD = "keyword"  # sparse only (BM25 / PostgreSQL FTS)
    SEMANTIC = "semantic"  # dense only (embeddings + Qdrant)
    HYBRID = "hybrid"  # both, fused with RRF


@dataclass(frozen=True, slots=True)
class IndexedVersion:
    document_id: uuid.UUID
    indexed_at: datetime | None
    embedding_model: str | None


@dataclass(slots=True)
class SearchScope:
    """What a search may see.

    `versions` is the user's whole searchable library (the current, indexed version
    of each paper) and defines collection statistics. The remaining fields restrict
    which passages may be *returned*; every retriever applies them before its own
    top-k cut.
    """

    user_id: uuid.UUID
    versions: dict[uuid.UUID, IndexedVersion]
    allowed_documents: set[uuid.UUID] | None = None  # None = every paper in `versions`
    section_kinds: set[str] | None = None  # None = every kind not excluded
    exclude_section_kinds: set[str] = field(default_factory=set)

    def allows(self, document_id: uuid.UUID, section_kind: str) -> bool:
        if self.allowed_documents is not None and document_id not in self.allowed_documents:
            return False
        if self.section_kinds is not None and section_kind not in self.section_kinds:
            return False
        return section_kind not in self.exclude_section_kinds

    @property
    def is_empty(self) -> bool:
        return not self.versions or (
            self.allowed_documents is not None and not self.allowed_documents
        )


@dataclass(slots=True)
class RetrievedPassage:
    chunk_id: uuid.UUID
    score: float
    matched_terms: dict[str, int] | None = None  # sparse retrievers that can explain matches
