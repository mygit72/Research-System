"""Index a BEIR corpus and run retrieval configs through this repo's own retrieval
primitives: the hand-written BM25Index, the sentence-transformers embedding provider
+ Qdrant vector store, ReciprocalRankFusion, and the local cross-encoder reranker.

This does not go through app.services.retrieval.service.search() (which is bound to
a SQLAlchemy session and the app's Document/Chunk ORM models — BEIR's corpus isn't a
user's uploaded papers). Instead it drives the same underlying classes directly, with
the same chunking config, the same analyzer, the same BM25 formula, the same fusion
formula, and the same models. See eval/beir/README.md for exactly what this does and
does not reuse.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND_ROOT = HERE.parent.parent / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
# Isolate this eval from the developer's own backend/.env (API keys, provider choice):
# only the explicit settings below apply, so results don't depend on local config drift.
os.environ.setdefault("NO_ENV_FILE", "1")

from app.core.config import Settings  # noqa: E402
from app.services.chunking import (  # noqa: E402
    ChunkDraft,
    Chunker,
    ChunkingConfig,
    ChunkingStrategy,
    ChunkSource,
    SourceParagraph,
    SourceSection,
    get_token_counter,
)
from app.services.embeddings import get_embedding_provider  # noqa: E402
from app.services.reranking import get_reranker  # noqa: E402
from app.services.retrieval.bm25 import BM25Index  # noqa: E402
from app.services.retrieval.fusion import ReciprocalRankFusion  # noqa: E402
from app.services.retrieval.sparse import passage_text  # noqa: E402
from app.services.retrieval.text import analyze  # noqa: E402
from app.services.vectorstore import VectorFilter, VectorPoint, collection_name, get_vector_store  # noqa: E402

from dataset import CorpusDoc  # noqa: E402

EVAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-0000000beef5")
_NAMESPACE = uuid.UUID("c6b3f2b0-2a9f-4e4e-9b1f-beef00000001")


@dataclass(slots=True)
class EvalChunk:
    key: str  # f"{doc_id}#{index}", unique across the corpus
    doc_id: str  # BEIR corpus _id (qrels are judged at this granularity)
    draft: ChunkDraft


def build_settings(qdrant_dir: Path, **overrides: object) -> Settings:
    """Settings with every retrieval default from app/core/config.py, pointed at an
    isolated, local-only Qdrant directory so this eval never touches the app's own
    embedded index."""
    return Settings(
        storage_dir=qdrant_dir,
        qdrant_url=None,
        embedding_provider="sentence_transformers",
        local_only=True,
        **overrides,  # type: ignore[arg-type]
    )


def chunk_corpus(docs: list[CorpusDoc], settings: Settings) -> list[EvalChunk]:
    """Run every document through the app's real Chunker with the app's configured
    strategy/size/overlap/contextual-header settings."""
    counter = get_token_counter(settings.embedding_model)
    config = ChunkingConfig(
        strategy=ChunkingStrategy(settings.chunking_strategy),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        contextual_headers=settings.contextual_chunk_headers,
    )
    chunker = Chunker(config, counter)
    chunks: list[EvalChunk] = []
    for doc in docs:
        text = (doc.text or doc.title).strip()
        if not text:
            continue
        source = ChunkSource(
            document_title=doc.title,
            full_text=text,
            page_spans={1: (0, len(text))},
            sections=[
                SourceSection(
                    key="abstract",
                    title="Abstract",
                    path=["Abstract"],
                    kind="abstract",
                    paragraphs=[
                        SourceParagraph(
                            text=text,
                            kind="text",
                            page_start=1,
                            page_end=1,
                            char_start=0,
                            char_end=len(text),
                        )
                    ],
                )
            ],
        )
        for i, draft in enumerate(chunker.chunk(source)):
            chunks.append(EvalChunk(key=f"{doc.doc_id}#{i}", doc_id=doc.doc_id, draft=draft))
    return chunks


def rerank_text(draft: ChunkDraft) -> str:
    header = draft.context_header or draft.section_title
    return f"{header}\n{draft.text}" if header else draft.text


# --- BM25 -----------------------------------------------------------------------------


def build_bm25(chunks: list[EvalChunk], settings: Settings) -> BM25Index:
    index = BM25Index(settings.bm25_k1, settings.bm25_b)
    for c in chunks:
        terms = analyze(passage_text(c.draft.section_title, c.draft.text))
        index.add(c.key, terms)
    return index


def bm25_search(index: BM25Index, query: str, limit: int) -> list[tuple[str, float]]:
    hits = index.search(analyze(query), limit)
    return [(h.key, h.score) for h in hits]


# --- Dense ------------------------------------------------------------------------------


def build_dense(chunks: list[EvalChunk], settings: Settings) -> tuple[str, dict[uuid.UUID, str]]:
    provider = get_embedding_provider(settings)
    store = get_vector_store(settings)
    vectors = provider.embed_documents([c.draft.embedding_text for c in chunks])
    dimension = int(vectors.shape[1])
    name = collection_name("eval_beir_chunks", provider.model_id, dimension)
    store.ensure_collection(name, dimension)
    key_to_uuid = {c.key: uuid.uuid5(_NAMESPACE, c.key) for c in chunks}
    points = [
        VectorPoint(
            id=key_to_uuid[c.key],
            vector=vectors[i],
            payload={"user_id": str(EVAL_USER_ID), "chunk_key": c.key, "doc_id": c.doc_id},
        )
        for i, c in enumerate(chunks)
    ]
    store.upsert(name, points)
    uuid_to_key = {v: k for k, v in key_to_uuid.items()}
    return name, uuid_to_key


def dense_search(
    settings: Settings, collection: str, uuid_to_key: dict[uuid.UUID, str], query: str, limit: int
) -> list[tuple[str, float]]:
    provider = get_embedding_provider(settings)
    store = get_vector_store(settings)
    vector = provider.embed_query(query)
    hits = store.search(collection, vector, VectorFilter(user_id=EVAL_USER_ID), limit)
    return [(uuid_to_key[h.id], h.score) for h in hits]


# --- Fusion + rerank ----------------------------------------------------------------------


def fuse(rankings: dict[str, list[tuple[str, float]]], rrf_k: int, limit: int) -> list[str]:
    fused = ReciprocalRankFusion(rrf_k).fuse(rankings, limit)  # type: ignore[arg-type]
    return [hit.key for hit in fused]  # type: ignore[misc]


def rerank_keys(
    reranker: object, query: str, keys: list[str], chunk_by_key: dict[str, EvalChunk]
) -> list[str]:
    texts = [rerank_text(chunk_by_key[k].draft) for k in keys]
    scores = reranker.score(query, texts)  # type: ignore[attr-defined]
    return [k for k, _ in sorted(zip(keys, scores, strict=True), key=lambda x: -x[1])]


def keys_to_docs(keys: list[str], chunk_by_key: dict[str, EvalChunk]) -> list[str]:
    """Dedupe a ranked chunk list to one row per parent document (BEIR qrels are
    judged at document granularity), keeping each document's best (first, since the
    chunk list is already best-first) rank."""
    seen: set[str] = set()
    docs: list[str] = []
    for key in keys:
        doc_id = chunk_by_key[key].doc_id
        if doc_id not in seen:
            seen.add(doc_id)
            docs.append(doc_id)
    return docs


__all__ = [
    "EVAL_USER_ID",
    "EvalChunk",
    "build_bm25",
    "build_dense",
    "build_settings",
    "bm25_search",
    "chunk_corpus",
    "dense_search",
    "fuse",
    "get_embedding_provider",
    "get_reranker",
    "keys_to_docs",
    "rerank_keys",
    "rerank_text",
]
