"""The in-process scheduler: claims due watches, advances their schedule, never double-enqueues.

Uses a stubbed `execute_run` (via the job handler's own reference to it) so these tests are
about scheduling mechanics only — the full run pipeline is covered by test_agent_watches_api.py.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import get_session_factory
from app.models.agent import AgentRun, AgentWatch, RunStatus, RunTrigger, WatchStatus
from app.models.base import utcnow
from app.workers import scheduler
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"


async def _user_id(client: AsyncClient) -> uuid.UUID:
    return uuid.UUID((await client.get(f"{API}/users/me")).json()["id"])


async def _make_watch(
    user_id: uuid.UUID, *, next_run_at: Any, status: str = WatchStatus.ACTIVE
) -> uuid.UUID:
    async with get_session_factory()() as session:
        watch = AgentWatch(
            user_id=user_id,
            name="Mine",
            query="retrieval",
            interval_hours=24,
            relevance_threshold=0.35,
            auto_import=False,
            status=status,
            next_run_at=next_run_at,
        )
        session.add(watch)
        await session.commit()
        return watch.id


@pytest.fixture
def stub_execute_run(monkeypatch: pytest.MonkeyPatch) -> list[uuid.UUID]:
    calls: list[uuid.UUID] = []

    async def stub(session_factory: Any, settings: Any, run_id: uuid.UUID, report: Any) -> dict:
        calls.append(run_id)
        return {"status": "succeeded", "found": 0, "kept": 0, "imported": 0}

    monkeypatch.setattr("app.workers.agent_watch.execute_run", stub)
    return calls


async def test_tick_enqueues_due_watches_and_advances_next_run_at(
    auth_client: AsyncClient, settings: Settings, stub_execute_run: list[uuid.UUID]
) -> None:
    user_id = await _user_id(auth_client)
    watch_id = await _make_watch(user_id, next_run_at=utcnow() - timedelta(hours=1))

    enqueued = await scheduler.tick(settings)
    assert enqueued == 1
    await get_dispatcher(settings).drain()

    async with get_session_factory()() as session:
        watch = await session.get(AgentWatch, watch_id)
        assert watch is not None
        # SQLite round-trips naive datetimes; compare naive-to-naive.
        assert watch.next_run_at > utcnow().replace(tzinfo=None)
        run = (
            await session.execute(select(AgentRun).where(AgentRun.watch_id == watch_id))
        ).scalar_one()
        assert run.trigger == RunTrigger.SCHEDULED
    assert len(stub_execute_run) == 1


async def test_tick_skips_watches_not_yet_due(
    auth_client: AsyncClient, settings: Settings, stub_execute_run: list[uuid.UUID]
) -> None:
    user_id = await _user_id(auth_client)
    await _make_watch(user_id, next_run_at=utcnow() + timedelta(hours=1))
    assert await scheduler.tick(settings) == 0
    assert stub_execute_run == []


async def test_tick_skips_paused_watches(
    auth_client: AsyncClient, settings: Settings, stub_execute_run: list[uuid.UUID]
) -> None:
    user_id = await _user_id(auth_client)
    await _make_watch(
        user_id, next_run_at=utcnow() - timedelta(hours=1), status=WatchStatus.PAUSED
    )
    assert await scheduler.tick(settings) == 0
    assert stub_execute_run == []


async def test_tick_does_not_double_enqueue_a_watch_with_a_run_already_in_flight(
    auth_client: AsyncClient, settings: Settings, stub_execute_run: list[uuid.UUID]
) -> None:
    user_id = await _user_id(auth_client)
    due_at = utcnow() - timedelta(hours=1)
    watch_id = await _make_watch(user_id, next_run_at=due_at)
    async with get_session_factory()() as session:
        session.add(
            AgentRun(
                watch_id=watch_id,
                user_id=user_id,
                status=RunStatus.QUEUED,
                trigger=RunTrigger.MANUAL,
            )
        )
        await session.commit()

    assert await scheduler.tick(settings) == 0
    assert stub_execute_run == []
    async with get_session_factory()() as session:
        watch = await session.get(AgentWatch, watch_id)
        assert watch is not None
        assert watch.next_run_at == due_at.replace(tzinfo=None)
