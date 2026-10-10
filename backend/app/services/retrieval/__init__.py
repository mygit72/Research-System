"""Retrieval: sparse (BM25 / PostgreSQL FTS), dense (Qdrant), fusion (RRF), search service."""

from app.services.retrieval.service import (
    PassageResult,
    SearchFilters,
    SearchOutcome,
    SearchRequest,
    facets,
    search,
)
from app.services.retrieval.types import SearchMode

__all__ = [
    "PassageResult",
    "SearchFilters",
    "SearchMode",
    "SearchOutcome",
    "SearchRequest",
    "facets",
    "search",
]
