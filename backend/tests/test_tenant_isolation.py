"""Cross-tenant matrix: every API route that takes an id refuses another user's resources.

Driven by the OpenAPI schema, so a new route with a path id fails this test until the
fixture below creates something for it — new endpoints can't silently skip the check.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import Settings
from app.core.database import get_session_factory
from app.demo import sample_papers as sp
from app.main import app
from app.models.user import User
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_indexing_api import upload

API = "/api/v1"
# Signed URLs, not session-authenticated: covered by the asset signature tests.
SKIP_PREFIXES = ("/api/v1/assets/",)
# Literal path values, not ids.
LITERALS = {"step": "questions", "page": "1"}


async def ok(response: Any, codes: tuple[int, ...] = (200, 201, 202)) -> Any:
    assert response.status_code in codes, f"{response.request.url}: {response.text}"
    return response.json() if response.content else None


@pytest.fixture
async def owned(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    """One of everything, owned by the signed-in user."""
    c, drain = auth_client, get_dispatcher(settings).drain
    docs = []
    for name, paper in (("lora", sp.LORA_PAPER), ("retrieval", sp.RETRIEVAL_PAPER)):
        data = sp.write_sample_pdf(paper, tmp_path / f"{name}.pdf").read_bytes()
        docs.append(await upload(c, settings, f"{name}.pdf", data))
    ids: dict[str, str] = {"document_id": docs[0]}
    collection = await ok(
        await c.post(f"{API}/collections", json={"name": "Mine", "document_ids": docs})
    )
    ids["collection_id"] = collection["id"]
    ids["note_id"] = (
        await ok(await c.post(f"{API}/notes", json={"content": "n", "document_id": docs[0]}))
    )["id"]
    ids["bookmark_id"] = (
        await ok(await c.post(f"{API}/bookmarks", json={"document_id": docs[0]}))
    )["id"]
    await ok(await c.put(f"{API}/documents/{docs[0]}/tags", json={"names": ["secret"]}))
    ids["tag_id"] = (await ok(await c.get(f"{API}/tags")))[0]["id"]
    conversation = await ok(await c.post(f"{API}/chat/conversations", json={}))
    ids["conversation_id"] = conversation["id"]
    await c.post(
        f"{API}/chat/conversations/{conversation['id']}/messages",
        json={"content": "What do adapters save?"},
    )
    ids["comparison_id"] = (
        await ok(await c.post(f"{API}/comparisons", json={"document_ids": docs}))
    )["id"]
    ids["report_id"] = (
        await ok(await c.post(f"{API}/literature-review", json={"document_ids": docs}))
    )["id"]
    ids["project_id"] = (
        await ok(
            await c.post(
                f"{API}/projects",
                json={"idea": "Cheaper fine-tuning of large language models on one GPU"},
            )
        )
    )["id"]
    await drain()
    dataset = await ok(await c.post(f"{API}/evaluation/datasets", json={"name": "Mine"}))
    ids["dataset_id"] = dataset["id"]
    hit = (await ok(await c.post(f"{API}/search", json={"query": "adapters", "mode": "keyword"})))[
        "results"
    ][0]
    item = await ok(
        await c.post(
            f"{API}/evaluation/datasets/{dataset['id']}/items",
            json={"question": "What do adapters save?", "chunk_ids": [hit["chunk_id"]]},
        )
    )
    ids["item_id"] = item["id"]
    ids["run_id"] = (
        await ok(await c.post(f"{API}/evaluation/datasets/{dataset['id']}/runs", json={}))
    )["id"]
    await drain()
    ids["job_id"] = (await ok(await c.get(f"{API}/jobs")))["items"][0]["id"]
    ids["entity_id"] = (await ok(await c.get(f"{API}/entities")))[0]["id"]
    ids["key"] = (await ok(await c.get(f"{API}/authors")))[0]["key"]
    ids["session_id"] = (await ok(await c.get(f"{API}/users/me/sessions")))[0]["id"]
    return ids


def routes_with_ids() -> list[tuple[str, str]]:
    out = []
    for path, operations in app.openapi()["paths"].items():
        if "{" in path and path.startswith(API) and not path.startswith(SKIP_PREFIXES):
            out.extend((method.upper(), path) for method in operations)
    return sorted(out, key=lambda r: (r[1], r[0]))


@pytest.mark.parametrize("admin", [False, True], ids=["another user", "an administrator"])
async def test_another_user_can_reach_none_of_my_resources(
    auth_client: AsyncClient, client: AsyncClient, owned: dict[str, str], admin: bool
) -> None:
    owner = auth_client.headers["Authorization"]
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    if admin:  # whoever runs the site has no more access through the app than anyone else
        me = (await client.get(f"{API}/users/me")).json()
        async with get_session_factory()() as session:
            await session.execute(
                update(User).where(User.id == uuid.UUID(me["id"])).values(is_admin=True)
            )
            await session.commit()
        assert (await client.get(f"{API}/users/me")).json()["is_admin"] is True

    routes = routes_with_ids()
    assert len(routes) > 60
    leaks = []
    for method, template in routes:
        names = re.findall(r"{(\w+)}", template)
        missing = [n for n in names if n not in owned and n not in LITERALS]
        assert not missing, f"{method} {template}: add a {missing} resource to the fixture"
        path = template
        for name in names:
            path = path.replace(f"{{{name}}}", owned.get(name) or LITERALS[name])
        body = None if method in ("GET", "DELETE") else {}
        response = await client.request(method, path, json=body)
        # Reads and deletes must say "not found"; writes must at least never succeed (an
        # invalid empty body may be rejected with 422 before ownership is checked).
        allowed = (404,) if body is None else (404, 422)
        if response.status_code not in allowed:
            leaks.append(f"{method} {template} → {response.status_code}")
    assert not leaks, "\n".join(leaks)

    # And nothing of mine was changed or deleted along the way.
    client.headers["Authorization"] = owner
    for path in (
        f"documents/{owned['document_id']}",
        f"collections/{owned['collection_id']}",
        f"chat/conversations/{owned['conversation_id']}",
        f"comparisons/{owned['comparison_id']}",
        f"reports/{owned['report_id']}",
        f"projects/{owned['project_id']}",
        f"evaluation/datasets/{owned['dataset_id']}",
        f"evaluation/runs/{owned['run_id']}",
    ):
        await ok(await client.get(f"{API}/{path}"), (200,))
    sessions = (await client.get(f"{API}/users/me/sessions")).json()
    assert owned["session_id"] in {s["id"] for s in sessions}
    notes = (await client.get(f"{API}/notes")).json()
    assert any(
        n["id"] == owned["note_id"] for n in (notes["items"] if isinstance(notes, dict) else notes)
    )
