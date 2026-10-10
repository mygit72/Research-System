"""Search indexing for a document version: chunk → embed (cached) → vector index.

Separate from parsing on purpose: if the embedding model is unavailable the
paper is still readable; it's marked "not searchable" with a retry, instead of
failing the whole upload.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.document import (
    Chunk,
    Document,
    DocumentMetadata,
    DocumentVersion,
    EmbeddingCache,
    IndexStatus,
    Page,
    Section,
)
from app.services.chunking import (
    ChunkDraft,
    Chunker,
    ChunkingConfig,
    ChunkingStrategy,
    get_token_counter,
    source_from_sections,
)
from app.services.embeddings import EmbeddingError, EmbeddingProvider, get_embedding_provider
from app.services.vectorstore import VectorPoint, collection_name, get_vector_store

log = get_logger(__name__)

Progress = Callable[[str, float, str | None], None]
EMBED_BATCH = 64


@dataclass
class IndexResult:
    chunks: int
    embedded: int  # newly computed
    cached: int  # reused from the embedding cache
    model_id: str
    dimension: int
    strategy: str
    timings_ms: dict[str, float]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def chunking_config(settings: Settings, strategy: str | None = None) -> ChunkingConfig:
    return ChunkingConfig(
        strategy=ChunkingStrategy(strategy or settings.chunking_strategy),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        contextual_headers=settings.contextual_chunk_headers,
    )


def token_counter_for(provider: EmbeddingProvider) -> Any:
    # Chunk limits are in the embedding model's own tokens when we can load its tokenizer.
    return get_token_counter(getattr(provider, "model_name", None))


async def _cached_vectors(
    session: AsyncSession, model_id: str, hashes: list[str]
) -> dict[str, np.ndarray]:
    found: dict[str, np.ndarray] = {}
    unique = list(dict.fromkeys(hashes))
    for start in range(0, len(unique), 500):
        result = await session.execute(
            select(EmbeddingCache).where(
                EmbeddingCache.model_id == model_id,
                EmbeddingCache.text_hash.in_(unique[start : start + 500]),
            )
        )
        for row in result.scalars():
            found[row.text_hash] = np.frombuffer(row.vector, dtype=np.float32)
    return found


async def index_version(
    session_factory: async_sessionmaker[AsyncSession],
    version_id: uuid.UUID,
    settings: Settings,
    progress: Progress,
) -> IndexResult:
    timings: dict[str, float] = {}
    provider = get_embedding_provider(settings)
    config = chunking_config(settings)

    # --- load structure -------------------------------------------------------------------
    async with session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        assert version is not None
        document = await session.get(Document, version.document_id)
        assert document is not None
        metadata = (
            await session.execute(
                select(DocumentMetadata).where(DocumentMetadata.version_id == version_id)
            )
        ).scalar_one_or_none()
        sections = list(
            (
                await session.execute(
                    select(Section)
                    .where(Section.version_id == version_id)
                    .order_by(Section.position)
                )
            ).scalars()
        )
        full_text = version.full_text or ""
        page_rows = (
            await session.execute(select(Page).where(Page.version_id == version_id))
        ).scalars()
        page_spans = {p.number: (p.char_start, p.char_end) for p in page_rows}
        owner = {
            "user_id": str(document.user_id),
            "document_id": str(document.id),
            "version_id": str(version_id),
            "doc_type": document.doc_type,
            "year": metadata.year if metadata else None,
        }
        title = document.title
        abstract = metadata.abstract if metadata else None
        keywords = metadata.keywords if metadata else []

    # --- chunk ---------------------------------------------------------------------------
    progress("chunking", 0.0, "Splitting the paper into passages")
    started = time.perf_counter()
    source = source_from_sections(title, full_text, page_spans, sections)
    embed_for_semantic = (
        provider.embed_documents if config.strategy == ChunkingStrategy.SEMANTIC else None
    )

    def run_chunker() -> list[ChunkDraft]:
        return Chunker(config, token_counter_for(provider), embed=embed_for_semantic).chunk(source)

    drafts = await asyncio.to_thread(run_chunker)
    timings["chunking"] = round((time.perf_counter() - started) * 1000, 1)

    chunk_ids = [uuid.uuid4() for _ in drafts]
    async with session_factory() as session:
        await session.execute(delete(Chunk).where(Chunk.version_id == version_id))
        session.add_all(
            Chunk(
                id=chunk_id,
                version_id=version_id,
                document_id=uuid.UUID(owner["document_id"]),
                user_id=uuid.UUID(owner["user_id"]),
                section_id=uuid.UUID(d.section_key) if d.section_key else None,
                chunk_index=index,
                strategy=config.strategy.value,
                kind=d.kind,
                text=d.text,
                context_header=d.context_header[:1000],
                section_title=d.section_title[:500],
                section_kind=d.section_kind,
                page_start=d.page_start,
                page_end=d.page_end,
                char_start=d.char_start,
                char_end=d.char_end,
                paragraph_index=d.paragraph_index,
                token_count=d.token_count,
                content_hash=d.content_hash,
                boxes=d.boxes,
            )
            for index, (chunk_id, d) in enumerate(zip(chunk_ids, drafts, strict=True))
        )
        await session.commit()

    # --- embed (with cache) ------------------------------------------------------------------
    started = time.perf_counter()
    texts = [d.embedding_text for d in drafts]
    doc_text = "\n\n".join(x for x in (title, abstract or "", ", ".join(keywords)) if x)
    texts_with_doc = [*texts, doc_text]
    hashes = [text_hash(t) for t in texts_with_doc]
    model_id = provider.model_id

    async with session_factory() as session:
        cached = await _cached_vectors(session, model_id, hashes)
    missing = [i for i, h in enumerate(hashes) if h not in cached]
    vectors: dict[str, np.ndarray] = dict(cached)
    for start in range(0, len(missing), EMBED_BATCH):
        batch = missing[start : start + EMBED_BATCH]
        progress(
            "embedding",
            start / max(len(missing), 1),
            f"Embedding passages ({start + len(batch)} of {len(missing)})",
        )
        embedded = await asyncio.to_thread(
            provider.embed_documents, [texts_with_doc[i] for i in batch]
        )
        for index, vector in zip(batch, embedded, strict=True):
            vectors[hashes[index]] = vector
    timings["embedding"] = round((time.perf_counter() - started) * 1000, 1)
    dimension = int(next(iter(vectors.values())).shape[0]) if vectors else provider.dimension

    if missing:
        async with session_factory() as session:
            known = await _cached_vectors(session, model_id, [hashes[i] for i in missing])
            session.add_all(
                EmbeddingCache(
                    model_id=model_id,
                    text_hash=h,
                    dimension=dimension,
                    vector=vectors[h].astype(np.float32).tobytes(),
                )
                for h in dict.fromkeys(hashes[i] for i in missing)
                if h not in known
            )
            await session.commit()

    # --- index ---------------------------------------------------------------------------
    progress("indexing", 0.0, "Adding passages to the search index")
    started = time.perf_counter()
    store = get_vector_store(settings)
    chunk_collection = collection_name("chunks", model_id, dimension)
    doc_collection = collection_name("documents", model_id, dimension)

    def write_index() -> None:
        store.ensure_collection(chunk_collection, dimension)
        store.ensure_collection(doc_collection, dimension)
        store.delete(chunk_collection, version_id=version_id)
        store.upsert(
            chunk_collection,
            [
                VectorPoint(
                    id=chunk_id,
                    vector=vectors[hashes[i]],
                    payload={
                        **owner,
                        "chunk_id": str(chunk_id),
                        "chunk_index": i,
                        "section_kind": drafts[i].section_kind,
                        "kind": drafts[i].kind,
                        "page_start": drafts[i].page_start,
                    },
                )
                for i, chunk_id in enumerate(chunk_ids)
            ],
        )
        store.upsert(
            doc_collection,
            [
                VectorPoint(
                    id=uuid.UUID(owner["document_id"]), vector=vectors[hashes[-1]], payload=owner
                )
            ],
        )

    await asyncio.to_thread(write_index)
    timings["indexing"] = round((time.perf_counter() - started) * 1000, 1)

    async with session_factory() as session:
        version = await session.get(DocumentVersion, version_id)
        document = await session.get(Document, uuid.UUID(owner["document_id"]))
        assert version is not None and document is not None
        version.embedding_model = model_id
        version.embedding_dimension = dimension
        version.chunking_strategy = config.strategy.value
        version.chunk_count = len(drafts)
        version.indexed_at = datetime.now(UTC)
        document.index_status = IndexStatus.INDEXED
        document.index_error = None
        await session.commit()

    metrics.inc("chunks_indexed_total", len(drafts), strategy=config.strategy.value)
    metrics.inc("embeddings_computed_total", len(missing), model=model_id)
    metrics.inc("embeddings_cache_hits_total", len(hashes) - len(missing), model=model_id)
    return IndexResult(
        chunks=len(drafts),
        embedded=len(missing),
        cached=len(hashes) - len(missing),
        model_id=model_id,
        dimension=dimension,
        strategy=config.strategy.value,
        timings_ms=timings,
    )


async def mark_index_failed(
    session_factory: async_sessionmaker[AsyncSession], document_id: uuid.UUID, message: str
) -> None:
    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is not None:
            document.index_status = IndexStatus.FAILED
            document.index_error = message
            await session.commit()


def remove_from_index(
    settings: Settings, document_id: uuid.UUID, versions: list[dict[str, Any]]
) -> None:
    """Delete every vector of a document (all versions / models it was indexed with)."""
    store = get_vector_store(settings)
    for version in versions:
        model, dimension = version.get("embedding_model"), version.get("embedding_dimension")
        if model and dimension:
            store.delete(collection_name("chunks", model, dimension), document_id=document_id)
            store.delete(collection_name("documents", model, dimension), document_id=document_id)


__all__ = [
    "EmbeddingError",
    "IndexResult",
    "chunking_config",
    "index_version",
    "mark_index_failed",
    "remove_from_index",
]
