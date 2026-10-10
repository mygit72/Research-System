from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.services.retrieval.types import SearchMode


class SearchFiltersIn(BaseModel):
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)
    year_from: int | None = Field(default=None, ge=1000, le=3000)
    year_to: int | None = Field(default=None, ge=1000, le=3000)
    authors: list[str] | None = Field(default=None, max_length=50)
    doc_types: list[str] | None = Field(default=None, max_length=10)
    section_kinds: list[str] | None = Field(default=None, max_length=20)
    include_references: bool = False
    collection_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    tags: list[str] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _year_order(self) -> SearchFiltersIn:
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not be after year_to")
        return self


class SearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    mode: SearchMode = SearchMode.HYBRID
    filters: SearchFiltersIn = Field(default_factory=SearchFiltersIn)
    limit: int = Field(default=20, ge=1, le=100)
    candidates: int | None = Field(default=None, ge=1, le=200, description="Per retriever")
    rerank: bool | None = Field(default=None, description="None: rerank if configured")
    rerank_candidates: int | None = Field(default=None, ge=1, le=100)
    debug: bool = False


class SearchDocument(BaseModel):
    id: uuid.UUID
    title: str
    authors_display: str
    year: int | None
    doc_type: str
    venue: str | None


class SearchHit(BaseModel):
    rank: int
    chunk_id: uuid.UUID
    document: SearchDocument
    text: str
    kind: str
    section_title: str
    section_kind: str
    page_start: int
    page_end: int
    char_start: int
    boxes: list[list[float]]
    score: float
    score_kind: str = Field(description="rerank | rrf | bm25 | fts | cosine")
    matched_by: list[str] = Field(description="Retrievers that found this passage")
    retriever_ranks: dict[str, int]
    fused_rank: int = Field(description="Rank before reranking")
    highlights: list[tuple[int, int]] = Field(description="Matched-term spans in `text`")
    snippet: tuple[int, int] = Field(description="Best excerpt of `text` to show")


class SearchOut(BaseModel):
    query: str
    mode: SearchMode
    status: str = Field(description="ok | no_results | empty_library")
    results: list[SearchHit]
    retrievers: list[str]
    reranker: str | None = Field(description="Model that reordered the results")
    searched_papers: int
    warnings: list[str]
    timings_ms: dict[str, float]
    trace: dict[str, Any] | None = None


class FacetValue(BaseModel):
    value: str
    count: int


class CollectionFacet(BaseModel):
    value: str  # collection id
    label: str  # its name
    count: int


class SearchFacets(BaseModel):
    papers: int
    indexed_papers: int
    year_min: int | None
    year_max: int | None
    doc_types: list[FacetValue]
    authors: list[FacetValue]
    section_kinds: list[FacetValue]
    suggestions: list[str]
    collections: list[CollectionFacet] = Field(default_factory=list)
    tags: list[FacetValue] = Field(default_factory=list)
