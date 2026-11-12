"""Regression tests for the production document-viewer bug.

Root cause: Render's free-tier disk is ephemeral. The original PDF (and any
derived page/thumbnail PNG rendered from it) can disappear at any point in a
container's life, not only between restarts. `app/api/routes/assets.py` served
these straight off disk with no fallback, so a missing file either 404'd
silently (thumbnail) or crashed with an unhandled `pymupdf.FileNotFoundError`
(page images) — which is *not* a subclass of the builtin `FileNotFoundError`,
so a naive `except FileNotFoundError` guard would have missed it too. Since
the Figures/Tables tabs crop figures out of the same rendered page image
(`ElementTabs.tsx`'s `FigurePreview`), the one broken endpoint took the whole
reader and the Figures tab down together.

The fix (`app.demo.shared_library.restore_version_file`, called from
`app.api.routes.assets._resolve_original`) makes the existing startup-only
restore available on every request that finds the file missing, scoped to the
three canonical demo documents only — other users' uploads have no packaged
backup and correctly still 404 instead of crashing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Environment, JobBackend, Settings
from app.core.signing import sign_scope
from app.models.document import Document, DocumentVersion
from app.services.storage import get_storage
from app.workers.dispatcher import get_dispatcher

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Overrides conftest's `settings`: demo_mode=True, so the on-demand
    self-heal path in the assets routes actually runs (it's a no-op otherwise,
    by design, for self-hosted deployments with a real persistent disk)."""
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
        reranker_provider="none",
        llm_provider="fake",
        verifier_provider="lexical",
        summary_auto=False,
        demo_mode=True,
    )


@pytest.fixture(autouse=True)
def _patch_repository_settings_lookup(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """`DocumentRepository.__init__` falls back to the module-level, globally
    cached `app.core.config.get_settings()` (not the FastAPI DI override) when
    no `demo_user_id` is passed in, which is how `DocumentService` constructs
    it. In production there's only one real `Settings` instance so this is
    harmless, but under the test harness's per-test `Settings` it means a
    second user can't see the demo-shared documents unless this is patched too
    — same pattern conftest.py already uses for the worker modules."""
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings)


async def _bootstrap(settings: Settings) -> tuple[object, dict]:
    from app.core.database import get_session_factory
    from app.demo.shared_library import ensure_shared_sample_library

    session_factory = get_session_factory()
    result = await ensure_shared_sample_library(settings, session_factory)
    await get_dispatcher(settings).drain()
    return session_factory, result


async def _attention_version(session_factory, settings: Settings) -> DocumentVersion:
    async with session_factory() as session:
        doc = (
            await session.execute(
                select(Document).where(
                    Document.user_id == settings.demo_user_id,
                    Document.original_filename == "attention-is-all-you-need.pdf",
                )
            )
        ).scalar_one()
        return await session.get(DocumentVersion, doc.current_version_id)


def _signed_url(path: str, version_id, settings: Settings) -> str:
    return f"{path}?{sign_scope(f'version:{version_id}', settings)}"


async def test_page_image_self_heals_after_mid_session_file_loss(
    auth_client: AsyncClient, settings: Settings
) -> None:
    """A page image request must self-heal and return a real PNG even when the
    original file disappears *during* the session (not just at the next
    restart) — reproduces the exact bug: broken image icon on every page."""
    session_factory, res = await _bootstrap(settings)
    assert res["status"] == "bootstrapped"

    storage = get_storage(settings)
    version = await _attention_version(session_factory, settings)
    assert version.paginated and version.page_count

    file_path = storage.path(version.storage_key)
    assert file_path.exists()
    file_path.unlink()  # simulate the ephemeral disk losing the file mid-session
    assert not file_path.exists()

    url = f"/api/v1/assets/versions/{version.id}/pages/1.png?w=800&{sign_scope(f'version:{version.id}', settings)}"
    resp = await auth_client.get(url)

    assert resp.status_code == 200, resp.text
    assert resp.content[:8] == PNG_MAGIC
    assert file_path.exists(), "self-heal must leave the original restored on disk"


async def test_thumbnail_self_heals_after_mid_session_file_loss(
    auth_client: AsyncClient, settings: Settings
) -> None:
    """Thumbnails are rendered once at processing time and never regenerated;
    the cached thumb.png must come back the same way page images do."""
    session_factory, _ = await _bootstrap(settings)
    storage = get_storage(settings)
    version = await _attention_version(session_factory, settings)
    assert version.has_thumbnail

    storage.path(version.storage_key).unlink()
    storage.delete_derived(version.id)  # the cached thumb.png is also gone

    resp = await auth_client.get(_signed_url(f"/api/v1/assets/versions/{version.id}/thumbnail.png", version.id, settings))

    assert resp.status_code == 200, resp.text
    assert resp.content[:8] == PNG_MAGIC


async def test_figure_crop_source_survives_file_loss(
    auth_client: AsyncClient, settings: Settings
) -> None:
    """The Figures tab crops figures out of the page image via the same
    `page_template` URL (see ElementTabs.tsx FigurePreview); verify the whole
    chain — structure extraction found figures, and the page image they're
    cropped from renders — survives the file going missing."""
    session_factory, _ = await _bootstrap(settings)
    storage = get_storage(settings)

    async with session_factory() as session:
        doc = (
            await session.execute(
                select(Document).where(
                    Document.user_id == settings.demo_user_id,
                    Document.original_filename == "attention-is-all-you-need.pdf",
                )
            )
        ).scalar_one()
        document_id = doc.id
        version_id = doc.current_version_id

    structure = (await auth_client.get(f"/api/v1/documents/{document_id}/structure")).json()
    figures = [e for e in structure["elements"] if e["kind"] == "figure"]
    assert figures, "Attention Is All You Need should have extracted figures"
    figure_page = figures[0]["page"]

    version = await _attention_version(session_factory, settings)
    storage.path(version.storage_key).unlink()

    resp = await auth_client.get(
        f"/api/v1/assets/versions/{version_id}/pages/{figure_page}.png?w=1200&"
        f"{sign_scope(f'version:{version_id}', settings)}"
    )
    assert resp.status_code == 200, resp.text
    assert resp.content[:8] == PNG_MAGIC


async def test_self_heal_does_not_restore_other_users_files(
    auth_client: AsyncClient, settings: Settings
) -> None:
    """Tenant isolation: the self-heal is scoped to the three packaged demo
    papers. A regular user's own upload has no packaged backup — losing its
    file must still 404 cleanly, never crash, and must never be silently
    replaced by demo content."""
    import io
    import uuid
    from app.core.database import get_session_factory
    from app.models.user import User
    from app.services.documents import DocumentService
    from app.services.jobs import JobService
    from app.services.storage import get_storage as _get_storage
    from app.workers.dispatcher import get_dispatcher as _get_dispatcher
    from fastapi import UploadFile

    session_factory = get_session_factory()
    storage = _get_storage(settings)
    other_user_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            User(
                id=other_user_id,
                email=f"{other_user_id}@example.com",
                password_hash="irrelevant",
                full_name="Other User",
                is_active=True,
            )
        )
        await session.commit()

        job_service = JobService(session, _get_dispatcher(settings))
        doc_service = DocumentService(session, settings, storage, job_service)
        # Minimal, valid single-page PDF.
        pdf_bytes = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
            b"trailer<</Root 1 0 R>>\n%%EOF"
        )
        upload = UploadFile(file=io.BytesIO(pdf_bytes), filename="my-own-paper.pdf")
        doc = await doc_service.upload(other_user_id, upload)
        await session.commit()
        version_id = doc.current_version_id
        storage_key = (await session.get(DocumentVersion, version_id)).storage_key

    storage.path(storage_key).unlink(missing_ok=True)

    resp = await auth_client.get(
        f"/api/v1/assets/versions/{version_id}/file?{sign_scope(f'version:{version_id}', settings)}"
    )
    assert resp.status_code == 404
    assert not storage.path(storage_key).exists(), "must not fabricate a file for a non-demo document"


async def test_recovery_is_idempotent_no_duplicates(app: object, settings: Settings) -> None:
    """Running the bootstrap/restore repeatedly (as happens on every container
    restart) must never create duplicate documents, versions, or files."""
    session_factory, res1 = await _bootstrap(settings)
    assert res1["status"] == "bootstrapped" and res1["total"] == 3

    for _ in range(2):
        res = await _bootstrap(settings)
        assert res[1]["status"] == "ready"
        assert res[1]["count"] == 3

    async with session_factory() as session:
        docs = (
            await session.execute(
                select(Document).where(Document.user_id == settings.demo_user_id)
            )
        ).scalars().all()
        assert len(docs) == 3
        for doc in docs:
            versions = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                )
            ).scalars().all()
            assert len(versions) == 1, f"expected exactly one version for {doc.original_filename}"


async def test_asset_urls_proxy_through_api_prefix(
    auth_client: AsyncClient, settings: Settings
) -> None:
    """The Vercel rewrite proxies `/api/:path*` to the Render backend; every
    signed asset URL the frontend is handed must live under that prefix or the
    proxy silently 404s them in production."""
    session_factory, _ = await _bootstrap(settings)
    async with session_factory() as session:
        doc = (
            await session.execute(
                select(Document).where(
                    Document.user_id == settings.demo_user_id,
                    Document.original_filename == "attention-is-all-you-need.pdf",
                )
            )
        ).scalar_one()
        document_id = doc.id

    detail = (await auth_client.get(f"/api/v1/documents/{document_id}")).json()
    assets = detail["assets"]
    assert assets["file"].startswith(settings.api_prefix + "/assets/")
    assert assets["page_template"].startswith(settings.api_prefix + "/assets/")
    assert assets["thumbnail"].startswith(settings.api_prefix + "/assets/")
