from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

# Before anything from `app` is imported: tests never read a developer's .env (see config.py).
os.environ.setdefault("NO_ENV_FILE", "1")

from app.api.deps import _memory_limiter
from app.core.config import Environment, JobBackend, Settings, get_settings
from app.core.database import dispose_engine, get_engine, init_engine
from app.main import create_app
from app.models import Base
from app.services.retrieval.sparse import reset_sparse_indexes
from app.services.vectorstore import close_vector_store
from app.workers.dispatcher import get_dispatcher, reset_dispatcher


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
        # Fast, deterministic, no model download; real models are covered separately.
        embedding_provider="hashing",
        # Retrieval tests check fused order; reranking tests opt in to the lexical reranker.
        reranker_provider="none",
        llm_provider="fake",  # deterministic, grounded answers; real models tested opt-in
        verifier_provider="lexical",
        # Summaries are requested explicitly in tests; auto-summary has its own test.
        summary_auto=False,
    )


@pytest.fixture
async def app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[object]:
    # Background jobs read settings globally; point them at the test settings too.
    monkeypatch.setattr("app.workers.documents.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.summaries.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.comparisons.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.topics.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.reports.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.projects.get_settings", lambda: settings)
    monkeypatch.setattr("app.workers.evaluation.get_settings", lambda: settings)
    init_engine(settings)
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    reset_dispatcher()
    reset_sparse_indexes()
    _memory_limiter.reset()
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    yield application
    await get_dispatcher(settings).drain()
    close_vector_store()
    await dispose_engine()
    reset_dispatcher()


@pytest.fixture
async def client(app: object) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def register(client: AsyncClient, email: str | None = None) -> dict[str, object]:
    email = email or f"user-{uuid.uuid4().hex[:8]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct-horse-42", "full_name": "Ada Researcher"},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.fixture
async def auth_client(client: AsyncClient) -> AsyncClient:
    tokens = await register(client)
    client.headers["Authorization"] = f"Bearer {tokens['access_token']}"
    return client
