"""Celery worker entrypoint.

Run with:  celery -A app.workers.celery_app worker --loglevel=INFO
"""

from __future__ import annotations

import asyncio
import uuid

from celery import Celery

from app.core.config import get_settings
from app.core.database import dispose_engine, get_session_factory, init_engine
from app.core.logging import configure_logging
from app.workers import handlers  # noqa: F401  (registers job handlers)
from app.workers.runner import execute_job

settings = get_settings()
configure_logging(settings.log_level, settings.log_json)

celery = Celery(
    "research_intelligence",
    broker=settings.redis_url or "redis://localhost:6379/0",
    backend=None,  # job state lives in PostgreSQL, not the Celery result backend
)
celery.conf.update(
    task_acks_late=True,  # re-deliver if a worker crashes mid-job
    worker_prefetch_multiplier=1,  # long jobs: don't hoard tasks
    task_serializer="json",
    accept_content=["json"],
)


async def _run(job_id: uuid.UUID) -> None:
    # Each task gets a fresh engine: asyncpg connections are bound to one event loop.
    init_engine(settings)
    try:
        await execute_job(job_id, get_session_factory())
    finally:
        await dispose_engine()


@celery.task(name="jobs.run")  # type: ignore[untyped-decorator]
def run_job(job_id: str) -> None:
    asyncio.run(_run(uuid.UUID(job_id)))
