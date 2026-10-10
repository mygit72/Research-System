"""Executes a single job by id. Shared by the inline and Celery backends."""

from __future__ import annotations

import time
import traceback
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.models.job import Job, JobStatus
from app.services.llm.user_models import activate, deactivate, load_user_model
from app.services.usage import JOB_FEATURES, usage_scope
from app.workers.registry import JobContext, JobFailedError, get_handler

log = get_logger(__name__)

GENERIC_FAILURE_MESSAGE = "Something went wrong while processing this task."


async def execute_job(job_id: uuid.UUID, session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            log.error("job_not_found", job_id=str(job_id))
            return
        if job.status not in (JobStatus.QUEUED, JobStatus.FAILED):
            log.info("job_skipped", job_id=str(job_id), status=job.status)
            return
        job.status, job.stage = JobStatus.RUNNING, "starting"
        job.started_at, job.attempts = datetime.now(UTC), job.attempts + 1
        job.error_message = job.error_detail = None
        ctx = JobContext(
            job_id=job.id,
            user_id=job.user_id,
            kind=job.kind,
            payload=dict(job.payload),
            subject_id=job.subject_id,
            session_factory=session_factory,
        )
        await session.commit()

    handler = get_handler(ctx.kind)
    started = time.perf_counter()
    with structlog.contextvars.bound_contextvars(
        job_id=str(job_id), job_kind=ctx.kind, user_id=str(ctx.user_id)
    ):
        status, result = JobStatus.FAILED, {}
        error_message: str | None = None
        error_detail: str | None = None
        try:
            if handler is None:
                raise JobFailedError(GENERIC_FAILURE_MESSAGE, f"No handler for '{ctx.kind}'")
            feature = JOB_FEATURES.get(ctx.kind, "other")
            async with session_factory() as session:  # the owner's model (Settings → AI)
                user_model = await load_user_model(session, ctx.user_id)
            token = activate(user_model)
            try:
                with usage_scope(ctx.user_id, feature, ctx.job_id):
                    result = await handler(ctx)
            finally:
                deactivate(token)
            status = JobStatus.SUCCEEDED
        except JobFailedError as exc:
            error_message, error_detail = exc.user_message, exc.detail
        except Exception:  # never let a job die silently
            error_message, error_detail = GENERIC_FAILURE_MESSAGE, traceback.format_exc()
        duration_ms = round((time.perf_counter() - started) * 1000, 1)

        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            job.status, job.finished_at = status, datetime.now(UTC)
            job.result = result or {}
            job.error_message, job.error_detail = error_message, error_detail
            if status == JobStatus.SUCCEEDED:
                job.stage, job.progress = "completed", 1.0
            else:
                job.stage = "failed"
            await session.commit()

        if status == JobStatus.SUCCEEDED:
            log.info("job_succeeded", duration_ms=duration_ms)
        else:
            log.error(
                "job_failed", duration_ms=duration_ms, error=error_message, detail=error_detail
            )
