"""Regression test: a regular (non-demo) user must be able to start a chat
scoped to a specific shared demo paper, not just the whole library.

Same bug class as search, facets, and similar-papers: `create_conversation`'s
ownership check for `document_ids` filtered strictly by Document.user_id ==
user.id with no demo-merge fallback. Confirmed live on the production demo:
POST /chat/conversations with document_ids=[<attention_paper_id>] returned
422 "Some of the selected papers don't exist." for a brand-new visitor, even
though library-scoped chat (no document_ids) worked fine end-to-end (it
reuses the already-fixed retrieval/service.py scope resolution).
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


async def test_regular_user_can_start_a_chat_scoped_to_a_demo_paper(
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
        document_id = str(attention.id)

    resp = await auth_client.post(
        "/api/v1/chat/conversations",
        json={"document_ids": [document_id], "title": "test"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["scope"] == "papers"
    assert body["document_ids"] == [document_id]
