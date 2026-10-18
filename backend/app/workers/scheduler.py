"""In-process scheduler for Research Watches: no Celery beat service exists in this stack, so a
background asyncio loop (started from `main.py`'s lifespan, same shape as the model-warmup task)
polls for due watches and enqueues a run for each. This is the one path that works identically
whether jobs run inline (dev/SQLite) or via Celery (docker): either way, this process can still
write a `Job` row and ask the dispatcher to pick it up.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import Settings
from app.core.database import get_session_factory, run_after_commit
from app.core.logging import get_logger
from app.models.agent import AgentRun, AgentWatch, RunStatus, RunTrigger, WatchStatus
from app.models.base import utcnow
from app.services.agent import WATCH_RUN_JOB
from app.services.jobs import JobService
from app.workers.dispatcher import get_dispatcher

log = get_logger(__name__)


async def tick(settings: Settings) -> int:
    """Claim every due watch and enqueue a run for it. Returns how many were enqueued."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        jobs = JobService(session, get_dispatcher(settings))
        now = utcnow()
        due = (
            await session.execute(
                select(AgentWatch).where(
                    AgentWatch.status == WatchStatus.ACTIVE, AgentWatch.next_run_at <= now
                )
            )
        ).scalars()
        enqueued = 0
        for watch in due:
            in_flight = await session.scalar(
                select(AgentRun.id).where(
                    AgentRun.watch_id == watch.id,
                    AgentRun.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
                )
            )
            if in_flight is not None:
                continue  # a manual run is already in flight for this watch
            advanced = now + timedelta(
                hours=max(watch.interval_hours, settings.agent_watch_min_interval_hours)
            )
            result = await session.execute(
                update(AgentWatch)
                .where(AgentWatch.id == watch.id, AgentWatch.next_run_at <= now)
                .values(next_run_at=advanced)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:  # type: ignore[attr-defined]
                continue  # claimed by a concurrent tick; SQLite-safe (no SELECT ... FOR UPDATE)
            run = AgentRun(
                watch_id=watch.id,
                user_id=watch.user_id,
                status=RunStatus.QUEUED,
                trigger=RunTrigger.SCHEDULED,
            )
            session.add(run)
            await session.flush()
            await jobs.enqueue(
                watch.user_id,
                WATCH_RUN_JOB,
                payload={"watch_id": str(watch.id), "run_id": str(run.id)},
                subject_type="agent_run",
                subject_id=run.id,
            )
            enqueued += 1
        await session.commit()
        # Outside a request: nothing calls this automatically, so every job enqueued above
        # would otherwise sit registered but never dispatched.
        run_after_commit(session)
    return enqueued


async def run_scheduler(settings: Settings) -> None:
    while True:
        try:
            await tick(settings)
        except Exception:
            log.exception("agent_scheduler_tick_failed")
        await asyncio.sleep(settings.agent_scheduler_poll_seconds)
