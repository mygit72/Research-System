"""Startup recovery for jobs interrupted by a stopped or crashed server.

With the inline backend, jobs run inside the API process: a restart (or the OS killing it
under memory pressure) leaves them "running" forever, and their papers or reports stuck
"processing". On startup:

- a job that was running is queued again — work resumes, as the handlers can start over
  (each writes its result at the end, or replaces what it wrote before);
- unless it has already been interrupted `MAX_ATTEMPTS` times: then it is failed (a job that
  keeps killing the process must not run on every start), and its kind's `on_interrupted`
  hook marks the paper / report / run failed with a message the user can act on;
- jobs still queued are dispatched (they were lost with the process).

With Celery, jobs live in the broker and workers outlive API restarts, so this is skipped.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.workers.dispatcher import JobDispatcher
from app.workers.registry import JobContext, get_interrupt_handler

log = get_logger(__name__)

MAX_ATTEMPTS = 3
GAVE_UP = (
    "This stopped {attempts} times because the server was interrupted while it ran, so it "
    "wasn't started again. Try again — if it keeps happening, the machine may be short of memory."
)


async def recover_interrupted_jobs(
    session_factory: async_sessionmaker[AsyncSession], dispatcher: JobDispatcher
) -> dict[str, Any]:
    resume: list[uuid.UUID] = []
    gave_up: list[tuple[JobContext, str]] = []
    async with session_factory() as session:
        jobs = (
            await session.execute(
                select(Job)
                .where(Job.status.in_([JobStatus.RUNNING, JobStatus.QUEUED]))
                .order_by(Job.created_at)
            )
        ).scalars()
        for job in jobs:
            if job.status == JobStatus.RUNNING and job.attempts >= MAX_ATTEMPTS:
                message = GAVE_UP.format(attempts=job.attempts)
                job.status, job.stage = JobStatus.FAILED, "failed"
                job.error_message = message
                job.error_detail = "interrupted: the process stopped while the job was running"
                job.finished_at = datetime.now(UTC)
                gave_up.append(
                    (
                        JobContext(
                            job_id=job.id,
                            user_id=job.user_id,
                            kind=job.kind,
                            payload=dict(job.payload),
                            subject_id=job.subject_id,
                            session_factory=session_factory,
                        ),
                        message,
                    )
                )
            else:
                if job.status == JobStatus.RUNNING:
                    job.status, job.stage, job.stage_detail = JobStatus.QUEUED, "queued", None
                resume.append(job.id)
        await session.commit()

    for ctx, message in gave_up:
        handler = get_interrupt_handler(ctx.kind)
        if handler is None:
            continue
        try:
            await handler(ctx, message)
        except Exception as exc:  # recovery must not stop the server from starting
            log.warning("interrupt_handler_failed", job_id=str(ctx.job_id), error=repr(exc))
    for job_id in resume:
        dispatcher.dispatch(job_id)
    if resume or gave_up:
        log.info("jobs_recovered", resumed=len(resume), failed=len(gave_up))
    return {"resumed": len(resume), "failed": len(gave_up)}
