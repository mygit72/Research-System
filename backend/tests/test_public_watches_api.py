"""The public, no-login watch view: 404 unless explicitly made public, and only arXiv-public
fields are ever returned — never document_id, import_status, or anything about the owner."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.config import Settings
from app.workers.dispatcher import get_dispatcher
from tests.test_agent_watches_api import make_watch, pdf, serve  # noqa: F401 (fixtures)

API = "/api/v1"


async def test_a_private_watch_is_not_reachable(auth_client: AsyncClient) -> None:
    watch = await make_watch(auth_client)
    assert (await auth_client.get(f"{API}/public/watches/{watch['id']}")).status_code == 404
    assert (
        await auth_client.get(f"{API}/public/watches/{watch['id']}/digest")
    ).status_code == 404


async def test_a_nonexistent_watch_404s(auth_client: AsyncClient) -> None:
    assert (await auth_client.get(f"{API}/public/watches/{uuid.uuid4()}")).status_code == 404


async def test_a_public_watch_exposes_only_safe_fields(
    auth_client: AsyncClient, settings: Settings, serve: list[str]  # noqa: F811
) -> None:
    watch = await make_watch(auth_client, is_public=True, relevance_threshold=0.0)
    await auth_client.post(f"{API}/watches/{watch['id']}/run")
    await get_dispatcher(settings).drain()

    public = await auth_client.get(f"{API}/public/watches/{watch['id']}")
    assert public.status_code == 200
    body = public.json()
    assert body.keys() == {"id", "name", "query", "status", "created_at"}

    digest = await auth_client.get(f"{API}/public/watches/{watch['id']}/digest")
    assert digest.status_code == 200
    items = digest.json()["items"]
    assert items
    entry = items[0]
    assert entry.keys() == {
        "id",
        "arxiv_id",
        "title",
        "authors",
        "abstract",
        "published",
        "score",
        "blurb",
        "created_at",
    }
    assert "document_id" not in entry
    assert "import_status" not in entry
    assert "trace" not in entry


async def test_an_unauthenticated_client_can_read_the_public_endpoint(
    client: AsyncClient, auth_client: AsyncClient
) -> None:
    watch = await make_watch(auth_client, is_public=True)
    # `client` carries no Authorization header at all.
    response = await client.get(f"{API}/public/watches/{watch['id']}")
    assert response.status_code == 200
