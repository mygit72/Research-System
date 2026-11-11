"""Job dispatch backends.

`InlineDispatcher` runs jobs as asyncio tasks in the API process — zero extra
infrastructure, ideal for local development and tests. `CeleryDispatcher`
sends the job id to a Celery worker through Redis for production workloads
(parsing a 300-page PDF must not compete with API requests for CPU).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Protocol

from app.core.config import JobBackend, Settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.workers.runner import execute_job

log = get_logger(__name__)


class JobDispatcher(Protocol):
    def dispatch(self, job_id: uuid.UUID) -> None: ...

    async def drain(self) -> None:
        """Wait for locally running jobs (used by tests and graceful shutdown)."""
        ...


class InlineDispatcher:
    def __init__(self, max_concurrency: int = 2) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    def dispatch(self, job_id: uuid.UUID) -> None:
        task = asyncio.get_running_loop().create_task(self._run(job_id))
        self._tasks.add(task)  # hold a reference so the task isn't garbage-collected
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job_id: uuid.UUID) -> None:
        async with self._semaphore:
            await execute_job(job_id, get_session_factory())

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


class CeleryDispatcher:
    def dispatch(self, job_id: uuid.UUID) -> None:
        from app.workers.celery_app import run_job

        run_job.delay(str(job_id))

    async def drain(self) -> None:
        return None


_dispatcher: JobDispatcher | None = None


def get_dispatcher(settings: Settings) -> JobDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = (
            CeleryDispatcher()
            if settings.job_backend == JobBackend.CELERY
            else InlineDispatcher(max_concurrency=settings.inline_job_concurrency)
        )
        log.info("job_dispatcher_initialized", backend=settings.job_backend.value)
    return _dispatcher


def reset_dispatcher() -> None:
    global _dispatcher
    _dispatcher = None
