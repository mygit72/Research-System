"""Regression test: a regular (non-demo) user must see the shared demo papers
as "similar papers" results, not just themselves.

Same bug class as the search fix in services/retrieval/service.py: the vector
search itself (`PgVectorStore.search`) already auto-merges demo_user_id, so it
correctly found the other two demo papers as neighbours. But the two plain SQL
queries right after it -- loading the Document/DocumentMetadata rows for the
hits, and loading the whole library for IDF stats -- filtered strictly by
Document.user_id == user_id with no demo-merge fallback. Every demo-owned hit
got silently dropped by `if doc_id not in by_id: continue`, so a brand-new
visitor (no uploads of their own) always got an empty "similar papers" list.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import Environment, JobBackend, Settings
from app.workers.dispatcher import get_dispatcher


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}",
        redis_url=None,
        job_backend=JobBackend.INLINE,
        rate_limit_enabled=False,
        jwt_secret="test-secret-test-secret-test-secret-123",  # type: ignore[arg-type]
        storage_dir=tmp_path / "files",
        log_level="WARNING",
        embedding_provider="hashing",
        reranker_provider="lexical",
        llm_provider="fake",
        verifier_provider="lexical",
        summary_auto=False,
        demo_mode=True,
    )


@pytest.fixture(autouse=True)
def _patch_global_settings_lookup(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)


async def test_regular_user_sees_demo_siblings_as_similar_papers(
    app: object, auth_client: AsyncClient, settings: Settings
) -> None:
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library
    from app.models.document import Document
    from sqlalchemy import select

    session_factory = get_session_factory()
    await ensure_shared_sample_library(settings, session_factory)
    await get_dispatcher(settings).drain()

    async with session_factory() as session:
        attention = (
            await session.execute(
                select(Document).where(
                    Document.user_id == settings.demo_user_id,
                    Document.original_filename == "attention-is-all-you-need.pdf",
                )
            )
        ).scalar_one()
        document_id = attention.id

    resp = await auth_client.get(f"/api/v1/documents/{document_id}/similar")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ok", body
    assert body["items"], "a brand-new user must see the other demo papers as similar"
