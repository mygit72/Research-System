"""Registry of background job handlers.

A handler is an async function taking a `JobContext` and returning a JSON-able
result dict. Handlers report progress through `ctx.report()`, which writes to
the jobs table in its own transaction so the UI sees live progress.

    @job_handler("document.process")
    async def process_document(ctx: JobContext) -> dict[str, Any]:
        await ctx.report("parsing", 0.1)
        ...
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.job import Job


class JobFailedError(Exception):
    """Raise from a handler to fail with a user-safe message (no stack trace shown)."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


@dataclass
class JobContext:
    job_id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    subject_id: uuid.UUID | None
    session_factory: async_sessionmaker[AsyncSession]
    _last_progress: float = field(default=0.0, repr=False)

    async def report(self, stage: str, progress: float, detail: str | None = None) -> None:
        progress = max(self._last_progress, min(progress, 1.0))  # never go backwards
        self._last_progress = progress
        async with self.session_factory() as session:
            job = await session.get(Job, self.job_id)
            if job is not None:
                job.stage, job.progress, job.stage_detail = stage, progress, detail
                await session.commit()


JobHandler = Callable[[JobContext], Awaitable[dict[str, Any]]]

_HANDLERS: dict[str, JobHandler] = {}


def job_handler(kind: str) -> Callable[[JobHandler], JobHandler]:
    def decorator(func: JobHandler) -> JobHandler:
        if kind in _HANDLERS and _HANDLERS[kind] is not func:
            raise ValueError(f"Duplicate job handler for kind '{kind}'")
        _HANDLERS[kind] = func
        return func

    return decorator


def get_handler(kind: str) -> JobHandler | None:
    return _HANDLERS.get(kind)


# Called when a job is given up after the process running it died (see workers/recovery.py):
# the handler's own failure path never ran, so its subject (paper, report, …) would stay
# "processing" forever. Receives the job's context and a message to show.
InterruptHandler = Callable[[JobContext, str], Awaitable[None]]
_INTERRUPTED: dict[str, InterruptHandler] = {}


def on_interrupted(*kinds: str) -> Callable[[InterruptHandler], InterruptHandler]:
    def decorator(func: InterruptHandler) -> InterruptHandler:
        for kind in kinds:
            _INTERRUPTED[kind] = func
        return func

    return decorator


def get_interrupt_handler(kind: str) -> InterruptHandler | None:
    return _INTERRUPTED.get(kind)


def registered_kinds() -> list[str]:
    return sorted(_HANDLERS)
