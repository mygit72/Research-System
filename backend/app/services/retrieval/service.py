"""Search: scope → retrievers (concurrently) → fusion → reranking → passages with a trace.

    query ─┬─ sparse (BM25 / PG FTS) ─┐
           │                          ├─ RRF ─→ cross-encoder rerank ─→ passages + highlights
           └─ dense (Qdrant) ─────────┘   (top RERANK_CANDIDATES)

Filters on paper metadata (year, author, type, chosen papers) are resolved to a set
of documents in SQL first, so they always reflect the latest metadata edits, and
are then applied inside every retriever. Reference lists are excluded by default:
they're full of author names and venues that match queries without answering them.

If the embedding model is unavailable, hybrid search degrades to keyword search
with a visible warning instead of failing; likewise a failing reranker leaves the
fused order in place.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError, ValidationError
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.document import Chunk, Document, DocumentMetadata, DocumentStatus, DocumentVersion
from app.services.embeddings import EmbeddingError
from app.services.organization import (
    collection_counts,
    documents_matching,
    list_collections,
    list_tags,
)
from app.services.reranking import RerankError, get_reranker, score_cache
from app.services.retrieval.dense import DenseRetriever
from app.services.retrieval.fusion import FusedHit, ReciprocalRankFusion
from app.services.retrieval.sparse import get_sparse_retriever
from app.services.retrieval.text import analyze, highlight_spans
from app.services.retrieval.types import (
    IndexedVersion,
    RetrievedPassage,
    SearchMode,
    SearchScope,
)

log = get_logger(__name__)

MAX_QUERY_CHARS = 500
SNIPPET_CHARS = 320
DEFAULT_EXCLUDED_SECTIONS = {"references"}


@dataclass(slots=True)
class SearchFilters:
    document_ids: list[uuid.UUID] | None = None
    year_from: int | None = None
    year_to: int | None = None
    authors: list[str] | None = None
    doc_types: list[str] | None = None
    section_kinds: list[str] | None = None
    include_references: bool = False
    collection_ids: list[uuid.UUID] | None = None  # papers in any of these collections
    tags: list[str] | None = None  # papers with any of these tags

    @property
    def restricts_documents(self) -> bool:
        return bool(
            self.document_ids
            or self.collection_ids
            or self.tags
            or self.year_from is not None
            or self.year_to is not None
            or self.authors
            or self.doc_types
        )


@dataclass(slots=True)
class SearchRequest:
    query: str
    mode: SearchMode = SearchMode.HYBRID
    filters: SearchFilters = field(default_factory=SearchFilters)
    limit: int = 20  # passages returned
    candidates: int | None = None  # per retriever before fusion (default: settings.top_k)
    rerank: bool | None = None  # None = rerank if a reranker is configured
    rerank_candidates: int | None = None  # fused passages to rescore (default: settings)
    debug: bool = False


@dataclass(slots=True)
class PassageResult:
    rank: int
    chunk: Chunk
    document: Document
    metadata: DocumentMetadata | None
    score: float
    score_kind: str  # rerank | rrf | bm25 | cosine | fts
    matched_by: list[str]
    retriever_ranks: dict[str, int]
    fused_rank: int  # position before reranking (== rank when not reranked)
    highlights: list[tuple[int, int]]
    snippet: tuple[int, int]


@dataclass(slots=True)
class SearchOutcome:
    query: str
    mode: SearchMode
    status: str  # ok | no_results | empty_library
    results: list[PassageResult]
    timings_ms: dict[str, float]
    warnings: list[str]
    retrievers: list[str]
    searched_papers: int
    trace: dict[str, Any] | None = None
    reranker: str | None = None  # model that reordered the results, if any


# --- scope ------------------------------------------------------------------------------------


async def build_scope(
    session: AsyncSession, user_id: uuid.UUID, filters: SearchFilters
) -> SearchScope:
    from app.core.config import get_settings

    settings = get_settings()
    rows = await session.execute(
        select(
            Document.id,
            Document.year,
            Document.doc_type,
            DocumentVersion.id,
            DocumentVersion.indexed_at,
            DocumentVersion.embedding_model,
            DocumentMetadata.authors,
        )
        .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
        .outerjoin(DocumentMetadata, DocumentMetadata.version_id == DocumentVersion.id)
        .where(
            or_(Document.user_id == user_id, Document.user_id == settings.demo_user_id)
            if settings.demo_mode
            else (Document.user_id == user_id),
            Document.status == DocumentStatus.READY,
            DocumentVersion.indexed_at.is_not(None),
        )
    )
    versions: dict[uuid.UUID, IndexedVersion] = {}
    allowed: set[uuid.UUID] = set()
    organized = await documents_matching(
        session, user_id, collection_ids=filters.collection_ids, tags=filters.tags
    )
    wanted_ids = set(filters.document_ids or [])
    wanted_authors = {a.strip().casefold() for a in filters.authors or [] if a.strip()}
    wanted_types = {t.lower() for t in filters.doc_types or []}
    for doc_id, year, doc_type, version_id, indexed_at, model, authors in rows.all():
        versions[version_id] = IndexedVersion(doc_id, indexed_at, model)
        if wanted_ids and doc_id not in wanted_ids:
            continue
        if organized is not None and doc_id not in organized:
            continue
        if filters.year_from is not None and (year is None or year < filters.year_from):
            continue
        if filters.year_to is not None and (year is None or year > filters.year_to):
            continue
        if wanted_types and doc_type.lower() not in wanted_types:
            continue
        if wanted_authors:
            names = {str(a.get("name", "")).casefold() for a in authors or []}
            if not names & wanted_authors:
                continue
        allowed.add(doc_id)
    section_kinds = set(filters.section_kinds) if filters.section_kinds else None
    excluded = set()
    if not filters.include_references and not (section_kinds and "references" in section_kinds):
        excluded = set(DEFAULT_EXCLUDED_SECTIONS)
    return SearchScope(
        user_id=user_id,
        versions=versions,
        allowed_documents=allowed if filters.restricts_documents else None,
        section_kinds=section_kinds,
        exclude_section_kinds=excluded,
    )


# --- snippets ---------------------------------------------------------------------------------


def snippet_window(
    text: str, highlights: list[tuple[int, int]], size: int = SNIPPET_CHARS
) -> tuple[int, int]:
    """The `size`-char window holding the most highlights, snapped to word boundaries."""
    if len(text) <= size:
        return 0, len(text)
    best_start, best_count = 0, -1
    for start, _ in highlights:
        count = sum(1 for s, e in highlights if s >= start and e <= start + size)
        if count > best_count:
            best_start, best_count = start, count
    # A little leading context reads better than starting on the matched word.
    start = max(0, best_start - size // 6) if highlights else 0
    start = min(start, len(text) - size)
    if start > 0:
        space = text.rfind(" ", 0, start + 1)
        start = space + 1 if space >= 0 and start - space < 30 else start
    end = min(len(text), start + size)
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > start + size // 2 else end
    return start, end


# --- search -----------------------------------------------------------------------------------


async def _timed(coro: Any) -> tuple[Any, float]:
    started = time.perf_counter()
    result = await coro
    return result, round((time.perf_counter() - started) * 1000, 1)


def _dense_error_message(exc: Exception) -> str:
    if isinstance(exc, EmbeddingError):
        return exc.user_message
    if isinstance(exc, ServiceUnavailableError):
        return exc.message
    return "Semantic search is unavailable right now."


async def search(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, request: SearchRequest
) -> SearchOutcome:
    started = time.perf_counter()
    query = " ".join(request.query.split())
    if not query:
        raise ValidationError("Type something to search for.")
    if len(query) > MAX_QUERY_CHARS:
        raise ValidationError(f"Searches are limited to {MAX_QUERY_CHARS} characters.")
    timings: dict[str, float] = {}
    warnings: list[str] = []

    scope, timings["scope"] = await _timed(build_scope(session, user_id, request.filters))
    searched = (
        len(scope.versions) if scope.allowed_documents is None else len(scope.allowed_documents)
    )

    def outcome(status: str, results: list[PassageResult], trace: Any = None) -> SearchOutcome:
        timings["total"] = round((time.perf_counter() - started) * 1000, 1)
        metrics.inc("search_requests_total", mode=request.mode.value, status=status)
        metrics.observe("search_latency_ms", timings["total"], mode=request.mode.value)
        return SearchOutcome(
            query,
            request.mode,
            status,
            results,
            timings,
            warnings,
            retrievers,
            searched,
            trace,
            reranker_id,
        )

    retrievers: list[str] = []
    reranker_id: str | None = None
    if not scope.versions:
        return outcome("empty_library", [])

    candidates = max(request.limit, request.candidates or settings.top_k)
    sparse = get_sparse_retriever(settings) if request.mode != SearchMode.SEMANTIC else None
    dense = DenseRetriever(settings) if request.mode != SearchMode.KEYWORD else None

    rankings: dict[str, list[RetrievedPassage]] = {}
    if not scope.is_empty:
        # The dense branch never touches the session, so both can run at once.
        tasks: dict[str, Any] = {}
        if sparse is not None:
            tasks[sparse.name] = _timed(sparse.search(session, scope, query, candidates))
        if dense is not None:
            tasks[dense.name] = _timed(dense.search(session, scope, query, candidates))
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for name, result in zip(tasks, results, strict=True):
            if isinstance(result, BaseException):
                if name != "dense" or not isinstance(result, Exception):
                    raise result
                message = _dense_error_message(result)
                log.warning("dense_retrieval_failed", error=repr(result))
                if request.mode == SearchMode.SEMANTIC:
                    raise ServiceUnavailableError(
                        message, hint="Keyword search still works. Switch the search mode."
                    ) from result
                warnings.append(f"{message} Showing keyword matches only.")
                continue
            rankings[name], timings[name] = result
            retrievers.append(name)

    if dense is not None and "dense" in retrievers:
        stale = sum(1 for v in scope.versions.values() if v.embedding_model != dense.model_id)
        if stale:
            warnings.append(
                f"{stale} paper(s) were indexed with a different embedding model, so only "
                "keyword search finds them. Re-index them to include them in semantic search."
            )

    # --- fuse -------------------------------------------------------------------------------
    fusion_started = time.perf_counter()
    if len(rankings) > 1:
        fused = ReciprocalRankFusion(settings.rrf_k).fuse(
            {name: [(p.chunk_id, p.score) for p in ranking] for name, ranking in rankings.items()},
            candidates,
        )
        score_kind = "rrf"
    else:
        name, ranking = next(iter(rankings.items()), ("none", []))
        fused = ReciprocalRankFusion(settings.rrf_k).fuse(
            {name: [(p.chunk_id, p.score) for p in ranking]}, candidates
        )
        for hit in fused:  # a single retriever: show its own score, not an RRF value
            hit.score = hit.contributions[name].score
        score_kind = {"bm25": "bm25", "postgres_fts": "fts", "dense": "cosine"}.get(name, name)
    timings["fusion"] = round((time.perf_counter() - fusion_started) * 1000, 2)

    # --- load passages ----------------------------------------------------------------------
    load_started = time.perf_counter()
    wanted_ids = [hit.key for hit in fused]
    if request.debug:
        for ranking in rankings.values():
            wanted_ids.extend(p.chunk_id for p in ranking)
    chunks = await _load_chunks(session, user_id, list(dict.fromkeys(wanted_ids)))
    documents = await _load_documents(session, {c.document_id for c in chunks.values()})
    query_terms = set(analyze(query))

    timings["load"] = round((time.perf_counter() - load_started) * 1000, 1)

    # --- rerank -----------------------------------------------------------------------------
    order = [hit for hit in fused if hit.key in chunks]  # skip vectors of replaced passages
    fused_rank = {hit.key: i for i, hit in enumerate(order, start=1)}
    rerank_scores: dict[Any, float] = {}
    if request.rerank is not False and order:
        try:
            reranker = get_reranker(settings)
        except ServiceUnavailableError as exc:
            reranker = None
            warnings.append(f"{exc.message} Results are in fused order.")
        if reranker is None and request.rerank:
            warnings.append("Reranking is turned off on this server.")
        if reranker is not None:
            size = max(request.rerank_candidates or settings.rerank_candidates, request.limit)
            head = order[:size]
            rerank_started = time.perf_counter()
            try:
                scores, cached = await asyncio.to_thread(
                    score_cache.score,
                    reranker,
                    query,
                    [rerank_text(chunks[hit.key]) for hit in head],  # type: ignore[index]
                )
            except Exception as exc:  # never lose results because the reranker failed
                message = exc.user_message if isinstance(exc, RerankError) else "Reranking failed."
                log.warning("rerank_failed", error=repr(exc))
                warnings.append(f"{message} Results are in fused order.")
            else:
                rerank_scores = {hit.key: score for hit, score in zip(head, scores, strict=True)}
                # Only reranked passages are returned, so every result has a comparable score.
                order = sorted(head, key=lambda h: (-rerank_scores[h.key], fused_rank[h.key]))
                reranker_id = reranker.model_id
                timings["rerank"] = round((time.perf_counter() - rerank_started) * 1000, 1)
                metrics.observe("rerank_latency_ms", timings["rerank"], model=reranker_id)
                metrics.inc("rerank_scores_cached_total", cached, model=reranker_id)

    results: list[PassageResult] = []
    for hit in order[: request.limit]:
        chunk = chunks[hit.key]  # type: ignore[index]
        document, metadata = documents[chunk.document_id]
        highlights = highlight_spans(chunk.text, query_terms)
        reranked = hit.key in rerank_scores
        results.append(
            PassageResult(
                rank=len(results) + 1,
                chunk=chunk,
                document=document,
                metadata=metadata,
                score=rerank_scores[hit.key] if reranked else hit.score,
                score_kind="rerank" if reranked else score_kind,
                matched_by=sorted(hit.contributions),
                retriever_ranks={name: c.rank for name, c in hit.contributions.items()},
                fused_rank=fused_rank[hit.key],
                highlights=highlights,
                snippet=snippet_window(chunk.text, highlights),
            )
        )

    trace = None
    if request.debug:
        trace = _trace(
            query, query_terms, scope, rankings, fused, chunks, documents, settings, candidates
        )
        if rerank_scores:
            trace["stages"]["reranked"] = [
                {
                    "rank": rank,
                    "score": round(rerank_scores[hit.key], 4),
                    "fused_rank": fused_rank[hit.key],
                    **_describe(hit.key, chunks, documents),
                }
                for rank, hit in enumerate(order, start=1)
            ]
            trace["parameters"]["reranker"] = reranker_id
            trace["parameters"]["rerank_candidates"] = len(rerank_scores)
    return outcome("ok" if results else "no_results", results, trace)


async def _load_chunks(
    session: AsyncSession, user_id: uuid.UUID, ids: list[Any]
) -> dict[uuid.UUID, Chunk]:
    found: dict[uuid.UUID, Chunk] = {}
    for start in range(0, len(ids), 500):
        rows = await session.execute(
            select(Chunk).where(Chunk.id.in_(ids[start : start + 500]), Chunk.user_id == user_id)
        )
        found.update({c.id: c for c in rows.scalars()})
    return found


async def _load_documents(
    session: AsyncSession, ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[Document, DocumentMetadata | None]]:
    if not ids:
        return {}
    rows = await session.execute(
        select(Document, DocumentMetadata)
        .outerjoin(DocumentMetadata, DocumentMetadata.version_id == Document.current_version_id)
        .where(Document.id.in_(ids))
    )
    return {doc.id: (doc, meta) for doc, meta in rows.all()}


def rerank_text(chunk: Chunk) -> str:
    """What the cross-encoder reads: where the passage sits ("Paper › Section"), then the text."""
    header = chunk.context_header or chunk.section_title
    return f"{header}\n{chunk.text}" if header else chunk.text


def _describe(
    chunk_id: Any,
    chunks: dict[uuid.UUID, Chunk],
    documents: dict[uuid.UUID, tuple[Document, DocumentMetadata | None]],
) -> dict[str, Any]:
    chunk = chunks.get(chunk_id)
    if chunk is None:
        return {"chunk_id": str(chunk_id), "missing": True}
    document = documents[chunk.document_id][0]
    return {
        "chunk_id": str(chunk.id),
        "document_id": str(document.id),
        "document_title": document.title,
        "section_title": chunk.section_title,
        "page": chunk.page_start,
        "preview": chunk.text[:160],
    }


def _trace(
    query: str,
    query_terms: set[str],
    scope: SearchScope,
    rankings: dict[str, list[RetrievedPassage]],
    fused: list[FusedHit],
    chunks: dict[uuid.UUID, Chunk],
    documents: dict[uuid.UUID, tuple[Document, DocumentMetadata | None]],
    settings: Settings,
    candidates: int,
) -> dict[str, Any]:
    """Every stage's ranked list, for the "how was this found" panel."""

    def describe(chunk_id: Any) -> dict[str, Any]:
        return _describe(chunk_id, chunks, documents)

    stages: dict[str, Any] = {}
    for name, ranking in rankings.items():
        stages[name] = [
            {
                "rank": rank,
                "score": round(p.score, 4),
                "matched_terms": p.matched_terms,
                **describe(p.chunk_id),
            }
            for rank, p in enumerate(ranking, start=1)
        ]
    stages["fused"] = [
        {
            "rank": rank,
            "score": round(hit.score, 5),
            "contributions": {
                name: {"rank": c.rank, "score": round(c.score, 4), "rrf": round(c.contribution, 5)}
                for name, c in hit.contributions.items()
            },
            **describe(hit.key),
        }
        for rank, hit in enumerate(fused, start=1)
    ]
    return {
        "query": query,
        "query_terms": sorted(query_terms),
        "fusion": {"method": "rrf", "k": settings.rrf_k} if len(rankings) > 1 else None,
        "parameters": {
            "candidates_per_retriever": candidates,
            "sparse_retriever": settings.sparse_retriever,
            "bm25_k1": settings.bm25_k1,
            "bm25_b": settings.bm25_b,
            "embedding_model": settings.embedding_model,
            "excluded_sections": sorted(scope.exclude_section_kinds),
        },
        "stages": stages,
    }


# --- facets -----------------------------------------------------------------------------------


async def facets(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Filter options and suggested searches, all derived from the user's own library."""
    from app.core.config import get_settings

    settings = get_settings()
    collections = await list_collections(session, user_id)
    counts = await collection_counts(session, [c.id for c in collections])
    tags = await list_tags(session, user_id)
    user_cond = (
        or_(Document.user_id == user_id, Document.user_id == settings.demo_user_id)
        if settings.demo_mode
        else (Document.user_id == user_id)
    )
    rows = (
        await session.execute(
            select(Document, DocumentVersion.indexed_at, DocumentMetadata)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .outerjoin(DocumentMetadata, DocumentMetadata.version_id == DocumentVersion.id)
            .where(user_cond, Document.status == DocumentStatus.READY)
        )
    ).all()
    indexed = [(doc, meta) for doc, indexed_at, meta in rows if indexed_at is not None]
    years = [doc.year for doc, _ in indexed if doc.year]
    doc_types = Counter(doc.doc_type for doc, _ in indexed)
    authors: Counter[str] = Counter()
    keywords: Counter[str] = Counter()
    display: dict[str, str] = {}
    for _, meta in indexed:
        if meta is None:
            continue
        authors.update({str(a.get("name", "")).strip() for a in meta.authors if a.get("name")})
        for keyword in meta.keywords:
            key = keyword.strip().casefold()
            if key:
                keywords[key] += 1
                display.setdefault(key, keyword.strip())
    sections = await session.execute(
        select(Chunk.section_kind, func.count())
        .join(Document, Document.current_version_id == Chunk.version_id)
        .where(Chunk.user_id == user_id)
        .group_by(Chunk.section_kind)
    )
    return {
        "papers": len(rows),
        "indexed_papers": len(indexed),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
        "doc_types": [{"value": k, "count": v} for k, v in doc_types.most_common()],
        "authors": [{"value": k, "count": v} for k, v in authors.most_common(50)],
        "section_kinds": [
            {"value": kind, "count": count}
            for kind, count in sorted(sections.all(), key=lambda r: -r[1])
        ],
        # Most shared keywords first: they describe what the library is about.
        "suggestions": [display[k] for k, _ in keywords.most_common(4)],
        "collections": [
            {"value": str(c.id), "label": c.name, "count": counts.get(c.id, (0, 0))[0]}
            for c in collections
        ],
        "tags": [{"value": tag.name, "count": count} for tag, count in tags if count],
    }
