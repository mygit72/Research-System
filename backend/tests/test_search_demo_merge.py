"""Regression tests: a regular (non-demo) user must be able to search the
shared demo papers, not just see them listed.

Root cause found while verifying the production demo end-to-end: three
separate queries in the retrieval stack filtered strictly by
`Chunk.user_id == user_id` with no demo-merge fallback, unlike every other
user-scoped query in this codebase (`build_scope`, `facets`'s own document
query, `PostgresFTSRetriever`, `DocumentRepository`). Since public-demo
uploads are disabled, a new visitor's own chunk library is always empty, so
every search against the demo library silently returned zero results
(`status: "no_results"`) even though both retrievers (BM25 and dense) ran
successfully and found the right candidates — the final passage-loading step
threw them away.

- `_load_chunks` (service.py): loaded the fused hit IDs back into `Chunk`
  rows to build the response; the missing demo merge meant every demo chunk
  vanished right before being returned.
- `facets()`'s `section_kinds` breakdown (service.py): same gap, smaller
  blast radius (just that one facet).
- `PostgresFTSRetriever.search` referenced `self.settings` that was never
  set (`__init__` didn't exist), so switching `SPARSE_RETRIEVER=postgres`
  would have crashed immediately; dormant in production (default is `bm25`)
  but fixed alongside the others since it's the same subsystem.
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
    """`build_scope`/`facets` read settings via the module-level, globally cached
    `app.core.config.get_settings()` rather than the FastAPI DI override, which is
    harmless in production (one real Settings instance) but needs patching here so
    this test's per-test Settings actually reaches them."""
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)


async def test_regular_user_can_search_the_shared_demo_library(
    app: object, auth_client: AsyncClient, settings: Settings
) -> None:
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library

    session_factory = get_session_factory()
    await ensure_shared_sample_library(settings, session_factory)
    await get_dispatcher(settings).drain()

    resp = await auth_client.post(
        "/api/v1/search", json={"query": "attention mechanism transformer"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["searched_papers"] == 3
    assert body["status"] == "ok", body
    assert body["results"], "a brand-new user must find the shared demo papers' content"
    assert not body["warnings"], "no stale-embedding warning once properly indexed"
    assert {"bm25", "dense"} <= set(body["retrievers"])


async def test_search_facets_section_kinds_include_demo_chunks(
    app: object, auth_client: AsyncClient, settings: Settings
) -> None:
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library

    session_factory = get_session_factory()
    await ensure_shared_sample_library(settings, session_factory)
    await get_dispatcher(settings).drain()

    resp = await auth_client.get("/api/v1/search/facets")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["papers"] == 3
    assert body["section_kinds"], "section_kind counts must include the demo papers' chunks"
    assert sum(s["count"] for s in body["section_kinds"]) > 0


async def test_postgres_fts_retriever_is_constructible(settings: Settings) -> None:
    """Regression: PostgresFTSRetriever.search referenced self.settings with no
    __init__ setting it, an AttributeError waiting for SPARSE_RETRIEVER=postgres."""
    from app.services.retrieval.sparse import PostgresFTSRetriever

    retriever = PostgresFTSRetriever(settings)
    assert retriever.settings is settings
