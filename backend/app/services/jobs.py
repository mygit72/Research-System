from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import after_commit
from app.core.errors import NotFoundError
from app.models.job import Job, JobStatus
from app.repositories.jobs import JobRepository
from app.workers.dispatcher import JobDispatcher


class JobService:
    def __init__(self, session: AsyncSession, dispatcher: JobDispatcher) -> None:
        self.session = session
        self.dispatcher = dispatcher
        self.jobs = JobRepository(session)

    async def enqueue(
        self,
        user_id: uuid.UUID,
        kind: str,
        *,
        payload: dict[str, Any] | None = None,
        subject_type: str | None = None,
        subject_id: uuid.UUID | None = None,
    ) -> Job:
        """Create a job and dispatch it once the current transaction commits.

        Dispatching after commit guarantees the worker can see the job row (and any
        rows created alongside it, e.g. the uploaded document).
        """
        job = await self.jobs.add(
            Job(
                user_id=user_id,
                kind=kind,
                payload=payload or {},
                subject_type=subject_type,
                subject_id=subject_id,
            )
        )
        job_id = job.id
        after_commit(self.session, lambda: self.dispatcher.dispatch(job_id))
        return job

    async def get(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
        job = await self.jobs.get_for_user(job_id, user_id)
        if job is None:
            raise NotFoundError("Job not found.")
        return job

    async def retry(self, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
        job = await self.get(job_id, user_id)
        if job.status != JobStatus.FAILED:
            return job
        job.status, job.stage, job.progress = JobStatus.QUEUED, "queued", 0.0
        after_commit(self.session, lambda: self.dispatcher.dispatch(job_id))
        return job
