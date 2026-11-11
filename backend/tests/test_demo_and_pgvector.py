"""Tests for PgVectorStore and public demo mode behaviors."""

import uuid
import numpy as np
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


@pytest.mark.anyio
async def test_ensure_shared_sample_library_idempotence(
    app: object,
    settings: Settings,
) -> None:
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library, RESEARCH_PAPERS
    from app.models.document import Document
    from app.models.user import User
    from app.workers.dispatcher import get_dispatcher
    from sqlalchemy import select

    session_factory = get_session_factory()

    # First bootstrap
    res1 = await ensure_shared_sample_library(settings, session_factory)
    assert res1["status"] in ("bootstrapped", "ready")
    assert res1.get("total", res1.get("count")) == 3
    await get_dispatcher(settings).drain()

    # Check demo user
    async with session_factory() as session:
        user = await session.get(User, settings.demo_user_id)
        assert user is not None
        assert user.email == "demo.system@research-intelligence.local"
        assert user.password_hash == "!disabled-demo-system-account"
        assert user.is_active is True

        # Check documents are the 3 real research papers
        docs = (
            await session.execute(
                select(Document).where(Document.user_id == settings.demo_user_id)
            )
        ).scalars().all()
        assert len(docs) == 3
        filenames = {d.original_filename for d in docs}
        assert filenames == set(RESEARCH_PAPERS.keys())

    # Second bootstrap (must be idempotent and report ready without adding)
    res2 = await ensure_shared_sample_library(settings, session_factory)
    assert res2["status"] == "ready"
    assert res2["count"] == 3


@pytest.mark.anyio
async def test_shared_library_restores_missing_files(
    app: object,
    settings: Settings,
) -> None:
    """Simulate an ephemeral filesystem restart: delete stored PDFs, then verify
    that re-running ensure_shared_sample_library regenerates them and re-enqueues
    failed documents."""
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library
    from app.models.document import Document, DocumentStatus, DocumentVersion
    from app.services.storage import get_storage
    from app.workers.dispatcher import get_dispatcher
    from sqlalchemy import select

    session_factory = get_session_factory()
    storage = get_storage(settings)

    # Bootstrap first to have all 3 docs
    res = await ensure_shared_sample_library(settings, session_factory)
    assert res.get("total", res.get("count")) == 3
    await get_dispatcher(settings).drain()

    # Collect storage keys and delete the files from disk
    async with session_factory() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.user_id == settings.demo_user_id)
            )
        ).scalars().all()
        for doc in docs:
            if doc.current_version_id:
                version = await session.get(DocumentVersion, doc.current_version_id)
                if version:
                    file_path = storage.path(version.storage_key)
                    file_path.unlink(missing_ok=True)

            # Simulate a failed document (as would happen on Render)
            doc.status = DocumentStatus.FAILED
            doc.error_message = "The source file is no longer available on disk"
        await session.commit()

    # Re-run bootstrap — should detect missing files and restore them
    res2 = await ensure_shared_sample_library(settings, session_factory)
    assert res2["status"] == "ready"
    assert res2["count"] == 3
    assert res2["restored"] == 3
    assert res2["reenqueued"] == 3
    await get_dispatcher(settings).drain()

    # Verify files exist on disk again
    async with session_factory() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.user_id == settings.demo_user_id)
            )
        ).scalars().all()
        for doc in docs:
            if doc.current_version_id:
                version = await session.get(DocumentVersion, doc.current_version_id)
                if version:
                    file_path = storage.path(version.storage_key)
                    assert file_path.exists(), f"File not restored: {file_path}"


@pytest.mark.anyio
async def test_reconcile_legacy_synthetic_records(
    app: object,
    settings: Settings,
) -> None:
    """Verify that legacy synthetic demo records are cleanly replaced with the 3 real papers."""
    from app.core.database import get_session_factory
    from app.demo.shared_library import (
        ensure_shared_sample_library,
        RESEARCH_PAPERS,
        LEGACY_SYNTHETIC_FILENAMES,
    )
    from app.models.document import Document
    from app.models.user import User
    from sqlalchemy import select

    session_factory = get_session_factory()

    # Seed the demo user first, then seed a legacy synthetic doc under demo_user_id
    async with session_factory() as session:
        user = await session.get(User, settings.demo_user_id)
        if user is None:
            user = User(
                id=settings.demo_user_id,
                email="demo.system@research-intelligence.local",
                password_hash="!disabled-demo-system-account",
                full_name="Research Intelligence Demo",
                is_active=True,
            )
            session.add(user)
            await session.commit()

        legacy_doc = Document(
            user_id=settings.demo_user_id,
            title="Old Synthetic Paper",
            doc_type="pdf",
            original_filename="sample-hybrid-retrieval.pdf",
        )
        session.add(legacy_doc)
        await session.commit()

    # Run bootstrap
    res = await ensure_shared_sample_library(settings, session_factory)
    assert res.get("total", res.get("count")) == 3

    # Check that legacy doc was cleaned up and only 3 real papers remain
    async with session_factory() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.user_id == settings.demo_user_id)
            )
        ).scalars().all()
        assert len(docs) == 3
        filenames = {d.original_filename for d in docs}
        assert filenames == set(RESEARCH_PAPERS.keys())
        assert not filenames.intersection(LEGACY_SYNTHETIC_FILENAMES)



