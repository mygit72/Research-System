"""Sparse (lexical) retrievers behind one interface.

- `BM25Retriever`: the hand-written BM25 over an in-memory inverted index per user.
  The index is kept in sync with the database *incrementally*: each search compares
  the user's current indexed versions (one cheap query) with what the index holds,
  then removes stale versions and tokenizes only new ones. Because the database is
  the source of truth, this stays correct across API processes and Celery workers
  without any cross-process invalidation. Memory is bounded by an LRU over users.
- `PostgresFTSRetriever`: PostgreSQL full-text search (`tsvector` + GIN index,
  `ts_rank_cd`), the path for libraries too large to hold in memory.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.core.logging import get_logger
from app.models.document import Chunk
from app.services.retrieval.bm25 import BM25Index
from app.services.retrieval.text import analyze, fts_terms
from app.services.retrieval.types import RetrievedPassage, SearchScope

log = get_logger(__name__)


class SparseRetriever(Protocol):
    name: str

    async def search(
        self, session: AsyncSession, scope: SearchScope, query: str, limit: int
    ) -> list[RetrievedPassage]: ...


def passage_text(section_title: str, text: str) -> str:
    """What the lexical index sees: the passage plus its section title."""
    return f"{section_title}\n{text}" if section_title else text


# --- BM25 ------------------------------------------------------------------------------------


@dataclass
class _Library:
    index: BM25Index
    versions: dict[uuid.UUID, datetime | None] = field(default_factory=dict)
    # version → [(chunk id, terms)] so a version can be removed without a vocabulary scan
    version_chunks: dict[uuid.UUID, list[tuple[uuid.UUID, list[str]]]] = field(default_factory=dict)
    chunk_info: dict[uuid.UUID, tuple[uuid.UUID, str]] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BM25Retriever:
    name = "bm25"

    def __init__(self, k1: float = 1.2, b: float = 0.75, max_users: int = 32) -> None:
        self.k1 = k1
        self.b = b
        self.max_users = max_users
        self._libraries: OrderedDict[uuid.UUID, _Library] = OrderedDict()
        self._guard = threading.Lock()

    def _library(self, user_id: uuid.UUID) -> _Library:
        with self._guard:
            library = self._libraries.get(user_id)
            if library is None:
                library = _Library(BM25Index(self.k1, self.b))
                self._libraries[user_id] = library
                while len(self._libraries) > self.max_users:
                    evicted, _ = self._libraries.popitem(last=False)
                    log.info("bm25_library_evicted", user_id=str(evicted))
            self._libraries.move_to_end(user_id)
            library.index.k1, library.index.b = self.k1, self.b
            return library

    def reset(self) -> None:
        with self._guard:
            self._libraries.clear()

    async def _sync(self, session: AsyncSession, scope: SearchScope, library: _Library) -> None:
        wanted = {vid: v.indexed_at for vid, v in scope.versions.items()}
        stale = [vid for vid, at in library.versions.items() if wanted.get(vid, "gone") != at]
        added = [vid for vid, at in wanted.items() if library.versions.get(vid, "new") != at]
        if not stale and not added:
            return
        rows: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, str, str, str]] = []
        for start in range(0, len(added), 500):
            result = await session.execute(
                select(
                    Chunk.id,
                    Chunk.version_id,
                    Chunk.document_id,
                    Chunk.section_kind,
                    Chunk.section_title,
                    Chunk.text,
                ).where(Chunk.version_id.in_(added[start : start + 500]))
            )
            rows.extend(tuple(row) for row in result.all())  # type: ignore[misc]

        def apply() -> int:
            for vid in stale:
                for chunk_id, terms in library.version_chunks.pop(vid, []):
                    library.index.remove(chunk_id, terms)
                    library.chunk_info.pop(chunk_id, None)
                library.versions.pop(vid, None)
            for chunk_id, vid, document_id, section_kind, section_title, text in rows:
                terms = analyze(passage_text(section_title, text))
                library.index.add(chunk_id, terms)
                library.version_chunks.setdefault(vid, []).append((chunk_id, terms))
                library.chunk_info[chunk_id] = (document_id, section_kind)
            for vid in added:
                library.versions[vid] = wanted[vid]
            return len(rows)

        added_chunks = await asyncio.to_thread(apply)
        log.info(
            "bm25_library_synced",
            user_id=str(scope.user_id),
            removed_versions=len(stale),
            added_versions=len(added),
            added_passages=added_chunks,
            passages=library.index.size,
        )

    async def search(
        self, session: AsyncSession, scope: SearchScope, query: str, limit: int
    ) -> list[RetrievedPassage]:
        library = self._library(scope.user_id)
        async with library.lock:  # one sync/search at a time per user; searches take ms
            await self._sync(session, scope, library)
            terms = analyze(query)

            def allow(key: object) -> bool:
                info = library.chunk_info.get(key)  # type: ignore[call-overload]
                return info is not None and scope.allows(info[0], info[1])

            hits = await asyncio.to_thread(library.index.search, terms, limit, allow)
        return [RetrievedPassage(h.key, h.score, h.matched_terms) for h in hits]  # type: ignore[arg-type]

    def stats(self, user_id: uuid.UUID) -> dict[str, float]:
        library = self._libraries.get(user_id)
        if library is None:
            return {"passages": 0, "terms": 0, "avgdl": 0.0}
        index = library.index
        return {"passages": index.size, "terms": len(index.postings), "avgdl": index.avgdl}


# --- PostgreSQL full-text search --------------------------------------------------------------

# Must match the GIN expression index exactly (literal regconfig) or PostgreSQL won't use it.
_TSVECTOR = func.to_tsvector(literal_column("'english'::regconfig"), Chunk.text)


class PostgresFTSRetriever:
    name = "postgres_fts"

    async def search(
        self, session: AsyncSession, scope: SearchScope, query: str, limit: int
    ) -> list[RetrievedPassage]:
        if session.bind.dialect.name != "postgresql":
            raise ServiceUnavailableError(
                "PostgreSQL full-text search needs a PostgreSQL database.",
                hint="Set SPARSE_RETRIEVER=bm25 for SQLite.",
            )
        words = fts_terms(query)
        if not words:
            return []
        # OR semantics like BM25 (websearch_to_tsquery would require every word to match).
        tsquery = func.to_tsquery(literal_column("'english'::regconfig"), " | ".join(words))
        score = func.ts_rank_cd(_TSVECTOR, tsquery).label("score")
        user_cond = (
            or_(Chunk.user_id == scope.user_id, Chunk.user_id == self.settings.demo_user_id)
            if self.settings.demo_mode
            else (Chunk.user_id == scope.user_id)
        )
        statement = (
            select(Chunk.id, Chunk.document_id, Chunk.section_kind, score)
            .where(
                user_cond,
                Chunk.version_id.in_(list(scope.versions)),
                _TSVECTOR.op("@@")(tsquery),
            )
            .order_by(score.desc(), Chunk.id)
        )
        if scope.allowed_documents is not None:
            statement = statement.where(Chunk.document_id.in_(list(scope.allowed_documents)))
        if scope.section_kinds is not None:
            statement = statement.where(Chunk.section_kind.in_(list(scope.section_kinds)))
        if scope.exclude_section_kinds:
            statement = statement.where(
                Chunk.section_kind.not_in(list(scope.exclude_section_kinds))
            )
        rows = await session.execute(statement.limit(limit))
        return [RetrievedPassage(row.id, float(row.score)) for row in rows]


_bm25 = BM25Retriever()


def get_sparse_retriever(settings: Settings) -> SparseRetriever:
    if settings.sparse_retriever == "postgres":
        return PostgresFTSRetriever()
    if settings.sparse_retriever != "bm25":
        raise ServiceUnavailableError(f"Unknown sparse retriever “{settings.sparse_retriever}”.")
    _bm25.k1, _bm25.b = settings.bm25_k1, settings.bm25_b
    return _bm25


def reset_sparse_indexes() -> None:
    """Drop in-memory BM25 libraries (tests; they rebuild lazily from the database)."""
    _bm25.reset()
