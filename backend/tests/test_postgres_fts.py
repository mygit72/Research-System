"""PostgreSQL full-text retriever. Needs a migrated PostgreSQL: set TEST_POSTGRES_URL (CI does)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.models.document import Chunk, Document, DocumentVersion
from app.models.user import User
from app.services.retrieval.sparse import PostgresFTSRetriever
from app.services.retrieval.types import IndexedVersion, SearchScope

URL = os.getenv("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_POSTGRES_URL to a migrated database")

PASSAGES = [
    ("method", "The two ranked lists are fused with reciprocal rank fusion."),
    ("results", "Fusion improves recall at ten by seven points over BM25 alone."),
    ("method", "Low-rank adapters freeze the pretrained weights."),
    ("references", "Cormack et al. Reciprocal rank fusion outperforms Condorcet."),
]


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(str(URL))
    async with engine.connect() as connection:
        transaction = await connection.begin()
        async with AsyncSession(bind=connection, expire_on_commit=False) as db:
            yield db
        await transaction.rollback()  # leave the database as we found it
    await engine.dispose()


async def seed(db: AsyncSession) -> tuple[SearchScope, list[uuid.UUID]]:
    user = User(email=f"fts-{uuid.uuid4().hex[:8]}@example.com")
    db.add(user)
    await db.flush()
    document = Document(user_id=user.id, title="Paper", doc_type="pdf", original_filename="p.pdf")
    db.add(document)
    await db.flush()
    version = DocumentVersion(
        document_id=document.id,
        user_id=user.id,
        storage_key="k",
        file_hash="h",
        file_size=1,
        mime_type="application/pdf",
        original_filename="p.pdf",
    )
    db.add(version)
    await db.flush()
    ids = []
    for index, (kind, passage) in enumerate(PASSAGES):
        chunk = Chunk(
            version_id=version.id,
            document_id=document.id,
            user_id=user.id,
            chunk_index=index,
            strategy="section_aware",
            kind="text",
            text=passage,
            section_kind=kind,
            page_start=1,
            page_end=1,
            char_start=0,
            char_end=len(passage),
            token_count=10,
            content_hash=uuid.uuid4().hex,
        )
        db.add(chunk)
        await db.flush()
        ids.append(chunk.id)
    scope = SearchScope(
        user.id,
        {version.id: IndexedVersion(document.id, None, "m")},
        exclude_section_kinds={"references"},
    )
    return scope, ids


async def test_fulltext_ranks_filters_and_isolates(session: AsyncSession) -> None:
    scope, ids = await seed(session)
    retriever = PostgresFTSRetriever()

    hits = await retriever.search(session, scope, "reciprocal rank fusion", 10)
    found = [h.chunk_id for h in hits]
    assert found[0] == ids[0]  # all three terms beat a single one
    assert set(found) == {ids[0], ids[1], ids[2]}  # OR semantics ("low-rank" matches rank)
    assert ids[3] not in found  # reference lists excluded
    assert hits[0].score > hits[1].score > 0

    scope.section_kinds = {"results"}
    assert [h.chunk_id for h in await retriever.search(session, scope, "fusion", 10)] == [ids[1]]

    other = SearchScope(uuid.uuid4(), scope.versions)
    assert await retriever.search(session, other, "fusion", 10) == []
    assert await retriever.search(session, scope, "the and of", 10) == []

    # The migration's GIN index matches the query expression, so PostgreSQL can use it.
    index = await session.execute(
        text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_chunks_text_fts'")
    )
    assert "to_tsvector('english'::regconfig, text)" in index.scalar_one()
