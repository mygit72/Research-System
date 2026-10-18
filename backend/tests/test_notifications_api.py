"""Notifications: list, unread count, mark read / mark all read, ownership."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import get_session_factory
from app.services import notifications as notif
from tests.conftest import register

API = "/api/v1"


async def _seed(user_id: str, count: int = 3) -> None:
    async with get_session_factory()() as session:
        for i in range(count):
            await notif.create(
                session,
                uuid.UUID(user_id),
                kind="agent_watch_digest",
                title=f"Found {i}",
                body="x",
            )
        await session.commit()


async def test_list_and_unread_count(auth_client: AsyncClient) -> None:
    me = (await auth_client.get(f"{API}/users/me")).json()
    await _seed(me["id"])

    listed = (await auth_client.get(f"{API}/notifications")).json()
    assert listed["total"] == 3
    assert len(listed["items"]) == 3

    unread = (await auth_client.get(f"{API}/notifications/unread-count")).json()
    assert unread["unread"] == 3


async def test_mark_read_and_mark_all_read(auth_client: AsyncClient) -> None:
    me = (await auth_client.get(f"{API}/users/me")).json()
    await _seed(me["id"])
    items = (await auth_client.get(f"{API}/notifications")).json()["items"]

    marked = await auth_client.post(f"{API}/notifications/{items[0]['id']}/read")
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert (await auth_client.get(f"{API}/notifications/unread-count")).json()["unread"] == 2

    all_read = await auth_client.post(f"{API}/notifications/read-all")
    assert all_read.json()["marked"] == 2
    assert (await auth_client.get(f"{API}/notifications/unread-count")).json()["unread"] == 0


async def test_another_user_cannot_read_or_mark_my_notifications(
    auth_client: AsyncClient, client: AsyncClient
) -> None:
    me = (await auth_client.get(f"{API}/users/me")).json()
    await _seed(me["id"], count=1)
    mine = (await auth_client.get(f"{API}/notifications")).json()["items"][0]

    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert (await client.get(f"{API}/notifications")).json()["items"] == []
    assert (await client.post(f"{API}/notifications/{mine['id']}/read")).status_code == 404
