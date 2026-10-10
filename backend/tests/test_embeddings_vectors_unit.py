from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import httpx
import numpy as np
import pytest
from qdrant_client import QdrantClient

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.services.embeddings import (
    EmbeddingError,
    HashingEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    get_embedding_provider,
)
from app.services.embeddings.local import prefixes_for
from app.services.models.manager import ModelManager
from app.services.vectorstore import (
    QdrantVectorStore,
    VectorFilter,
    VectorPoint,
    collection_name,
)

# --- embeddings ---------------------------------------------------------------------------------


def test_hashing_embeddings_are_normalized_deterministic_and_lexical() -> None:
    provider = HashingEmbeddingProvider(dimension=256)
    vectors = provider.embed_documents(
        [
            "hybrid retrieval with reciprocal rank fusion",
            "reciprocal rank fusion for hybrid retrieval systems",
            "protein folding in molecular biology",
        ]
    )
    assert vectors.shape == (3, 256)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    assert np.array_equal(vectors, provider.embed_documents(
        [
            "hybrid retrieval with reciprocal rank fusion",
            "reciprocal rank fusion for hybrid retrieval systems",
            "protein folding in molecular biology",
        ]
    ))  # fmt: skip
    assert vectors[0] @ vectors[1] > vectors[0] @ vectors[2] + 0.3
    assert provider.embed_documents([]).shape == (0, 256)


@pytest.mark.parametrize(
    ("model", "query_prefix", "passage_prefix"),
    [
        ("BAAI/bge-small-en-v1.5", "Represent this sentence for searching relevant passages: ", ""),
        ("intfloat/e5-base-v2", "query: ", "passage: "),
        ("sentence-transformers/all-MiniLM-L6-v2", "", ""),
    ],
)
def test_query_passage_prefixes(model: str, query_prefix: str, passage_prefix: str) -> None:
    assert prefixes_for(model) == (query_prefix, passage_prefix)


def _openai_transport(calls: list[dict[str, object]], fail_first: int = 0) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) <= fail_first:
            return httpx.Response(429, headers={"retry-after": "0"})
        if body["model"] == "bad":
            return httpx.Response(400, json={"error": "bad model"})
        data = [
            {"index": i, "embedding": [float(len(text)), 1.0, 0.0]}
            for i, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})  # out of order on purpose

    return httpx.MockTransport(handler)


def test_openai_compatible_provider_batches_orders_and_retries() -> None:
    calls: list[dict[str, object]] = []
    provider = OpenAICompatibleEmbeddingProvider(
        "text-embedding-3-small",
        "sk-test",
        dimension=3,
        transport=_openai_transport(calls, fail_first=1),
    )
    texts = [f"t{'x' * i}" for i in range(100)]
    vectors = provider.embed_documents(texts)
    assert vectors.shape == (100, 3)
    raw_first = np.array([2.0, 1.0, 0.0]) / np.linalg.norm([2.0, 1.0, 0.0])
    assert np.allclose(vectors[1], raw_first)  # ordered by index, not response order
    assert len(calls) == 3  # one 429 retry + two batches (96 + 4)


def test_openai_compatible_provider_errors_are_user_safe() -> None:
    provider = OpenAICompatibleEmbeddingProvider(
        "bad", "sk-test", dimension=3, transport=_openai_transport([])
    )
    with pytest.raises(EmbeddingError, match="rejected") as info:
        provider.embed_documents(["x"])
    assert "sk-test" not in str(info.value.user_message)


def test_local_only_refuses_remote_embeddings() -> None:
    settings = Settings(
        embedding_provider="openai",
        embedding_api_key="sk",  # type: ignore[arg-type]
        local_only=True,
        embedding_model="text-embedding-3-small-local-only-test",
    )
    with pytest.raises(ServiceUnavailableError, match="LOCAL_ONLY"):
        get_embedding_provider(settings)


# --- model lifecycle ------------------------------------------------------------------------------


def test_model_manager_lazy_lru_and_idle_eviction() -> None:
    loads: list[str] = []
    manager = ModelManager(max_loaded=1, idle_seconds=3600)

    def loader(name: str):  # type: ignore[no-untyped-def]
        def load() -> str:
            loads.append(name)
            return name

        return load

    assert manager.get("a", loader("a")) == "a"
    assert manager.get("a", loader("a")) == "a"
    assert loads == ["a"]  # loaded once
    manager.get("b", loader("b"))
    assert [m["model"] for m in manager.status()] == ["b"]  # "a" evicted at capacity
    manager.idle_seconds = 0
    time.sleep(0.01)
    manager.get("c", loader("c"))
    assert loads == ["a", "b", "c"]


# --- vector store -----------------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> QdrantVectorStore:
    client = QdrantClient(path=str(tmp_path / "q"))
    yield QdrantVectorStore(client, is_local=True)  # type: ignore[misc]
    client.close()


def _point(user: uuid.UUID, doc: uuid.UUID, vector: list[float], **payload: object) -> VectorPoint:
    return VectorPoint(
        id=uuid.uuid4(),
        vector=np.asarray(vector, dtype=np.float32) / np.linalg.norm(vector),
        payload={"user_id": str(user), "document_id": str(doc), "version_id": str(doc), **payload},
    )


def test_vector_store_filters_isolation_and_deletes(store: QdrantVectorStore) -> None:
    name = collection_name("chunks", "BAAI/bge-small-en-v1.5", 3)
    assert name == "chunks__baai-bge-small-en-v1-5__3"
    store.ensure_collection(name, 3)
    alice, bob = uuid.uuid4(), uuid.uuid4()
    doc_a, doc_b, doc_c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    store.upsert(
        name,
        [
            _point(alice, doc_a, [1, 0, 0], section_kind="method", year=2021),
            _point(alice, doc_b, [0.9, 0.1, 0], section_kind="results", year=2024),
            _point(bob, doc_c, [1, 0, 0], section_kind="method", year=2024),
        ],
    )
    query = np.asarray([1, 0, 0], dtype=np.float32)
    hits = store.search(name, query, VectorFilter(user_id=alice), 10)
    assert {h.payload["document_id"] for h in hits} == {str(doc_a), str(doc_b)}  # never Bob's
    assert hits[0].score >= hits[1].score

    only_method = store.search(
        name, query, VectorFilter(user_id=alice, section_kinds=["method"]), 10
    )
    assert [h.payload["document_id"] for h in only_method] == [str(doc_a)]
    recent = store.search(name, query, VectorFilter(user_id=alice, year_min=2022), 10)
    assert [h.payload["document_id"] for h in recent] == [str(doc_b)]
    excluded = store.search(
        name, query, VectorFilter(user_id=alice, exclude_document_ids=[doc_a]), 10
    )
    assert [h.payload["document_id"] for h in excluded] == [str(doc_b)]

    store.delete(name, document_id=doc_a)
    assert store.count(name, VectorFilter(user_id=alice)) == 1
    store.delete(name, version_id=doc_b)
    assert store.count(name, VectorFilter(user_id=alice)) == 0
    assert store.count(name, VectorFilter(user_id=bob)) == 1
    assert store.search("missing", query, VectorFilter(user_id=alice), 5) == []


def test_vector_store_version_and_section_exclusion_filters(store: QdrantVectorStore) -> None:
    name = collection_name("chunks", "m", 3)
    store.ensure_collection(name, 3)
    user, old, new = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    current = _point(user, new, [1, 0, 0], section_kind="method")
    refs = _point(user, new, [1, 0, 0], section_kind="references")
    store.upsert(name, [_point(user, old, [1, 0, 0], section_kind="method"), current, refs])
    query = np.asarray([1, 0, 0], dtype=np.float32)
    hits = store.search(
        name,
        query,
        VectorFilter(user_id=user, version_ids=[new], exclude_section_kinds=["references"]),
        10,
    )
    assert [h.id for h in hits] == [current.id]  # old version and reference list filtered
    vector = store.get_vector(name, current.id)
    assert vector is not None and np.allclose(vector, current.vector)
    assert store.get_vector(name, uuid.uuid4()) is None


def test_embedded_store_is_safe_under_concurrent_threads(store: QdrantVectorStore) -> None:
    """Regression: concurrent indexing jobs corrupted embedded Qdrant's SQLite transactions."""
    from concurrent.futures import ThreadPoolExecutor

    name = collection_name("chunks", "m", 3)
    store.ensure_collection(name, 3)
    user = uuid.uuid4()
    rng = np.random.default_rng(0)
    query = np.asarray([1, 0, 0], dtype=np.float32)

    def work(i: int) -> None:
        doc = uuid.uuid4()
        store.upsert(name, [_point(user, doc, list(rng.random(3) + 0.1)) for _ in range(20)])
        store.search(name, query, VectorFilter(user_id=user), 5)
        if i % 3 == 0:
            store.delete(name, document_id=doc)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(work, range(24)))  # re-raises any worker exception
    assert store.count(name, VectorFilter(user_id=user)) == 16 * 20


# --- real model (opt-in: RUN_MODEL_TESTS=1, downloads ~130 MB once) ------------------------------------


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1")
def test_bge_small_ranks_relevant_passage_first() -> None:
    from app.services.embeddings import SentenceTransformerProvider

    provider = SentenceTransformerProvider("BAAI/bge-small-en-v1.5", ModelManager(), device="cpu")
    passages = provider.embed_documents(
        [
            "Low-rank adaptation freezes pretrained weights and learns small update matrices.",
            "The dataset contains 2,400 expert-written questions about computer science papers.",
            "We train convolutional networks for image segmentation of medical scans.",
        ]
    )
    query = provider.embed_query("How can I fine-tune a large model cheaply?")
    scores = passages @ query
    assert int(np.argmax(scores)) == 0
    assert provider.dimension == 384
