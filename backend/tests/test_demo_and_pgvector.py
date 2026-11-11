"""Tests for PgVectorStore and public demo mode behaviors."""

import uuid
import numpy as np
import pytest

from app.core.config import Settings
from app.core.errors import PermissionDeniedError
from app.services.vectorstore import (
    PgVectorStore,
    QdrantVectorStore,
    VectorFilter,
    VectorPoint,
    get_vector_store,
)


@pytest.fixture
def demo_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        vector_store="pgvector",
        demo_mode=True,
        demo_user_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        uploads_enabled=False,
    )


def test_pgvector_store_in_memory_simulation(demo_settings: Settings) -> None:
    store = PgVectorStore(demo_settings)
    store.ensure_collection("chunks__test__3", dimension=3)

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    demo_user = demo_settings.demo_user_id

    doc_a = uuid.uuid4()
    doc_demo = uuid.uuid4()

    # Point 1: user A
    p1 = VectorPoint(
        id=uuid.uuid4(),
        vector=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        payload={"user_id": str(user_a), "document_id": str(doc_a), "year": 2024},
    )
    # Point 2: shared demo user
    p2 = VectorPoint(
        id=uuid.uuid4(),
        vector=np.array([0.9, 0.1, 0.0], dtype=np.float32),
        payload={"user_id": str(demo_user), "document_id": str(doc_demo), "year": 2023},
    )
    # Point 3: user B (private)
    p3 = VectorPoint(
        id=uuid.uuid4(),
        vector=np.array([1.0, 0.0, 0.0], dtype=np.float32),
        payload={"user_id": str(user_b), "document_id": str(uuid.uuid4()), "year": 2024},
    )

    store.upsert("chunks__test__3", [p1, p2, p3])
    assert store.count("chunks__test__3") == 3

    # Search as User A: should find p1 AND p2 (demo user), but NEVER p3 (user B)
    query_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    flt_a = VectorFilter(user_id=user_a)
    hits = store.search("chunks__test__3", query_vec, flt_a, limit=10)

    hit_ids = [h.id for h in hits]
    assert p1.id in hit_ids
    assert p2.id in hit_ids
    assert p3.id not in hit_ids
    assert hits[0].score > 0.99  # p1 exact match

    # Test filtering by year
    flt_year = VectorFilter(user_id=user_a, year_min=2024)
    hits_year = store.search("chunks__test__3", query_vec, flt_year, limit=10)
    assert len(hits_year) == 1
    assert hits_year[0].id == p1.id

    # Test get_vector and get_vectors
    vec = store.get_vector("chunks__test__3", p1.id)
    assert vec is not None
    assert np.allclose(vec, [1.0, 0.0, 0.0])

    vecs = store.get_vectors("chunks__test__3", [p1.id, p2.id])
    assert len(vecs) == 2

    # Test delete
    store.delete("chunks__test__3", document_id=doc_a)
    assert store.count("chunks__test__3") == 2
    assert store.get_vector("chunks__test__3", p1.id) is None


def test_vector_store_factory_switching() -> None:
    qdrant_settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        vector_store="qdrant",
    )
    pg_settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        vector_store="pgvector",
    )

    s1 = get_vector_store(qdrant_settings)
    assert isinstance(s1, QdrantVectorStore)

    s2 = get_vector_store(pg_settings)
    assert isinstance(s2, PgVectorStore)

