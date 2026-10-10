from __future__ import annotations

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession, JobServiceDep
from app.models.job import JobStatus
from app.repositories.jobs import JobRepository
from app.schemas.common import Page
from app.schemas.job import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=Page[JobResponse])
async def list_jobs(
    user: CurrentUser,
    db: DbSession,
    status: list[JobStatus] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[JobResponse]:
    jobs, total = await JobRepository(db).list_for_user(
        user.id, statuses=status, limit=limit, offset=offset
    )
    return Page(
        items=[JobResponse.model_validate(j) for j in jobs], total=total, limit=limit, offset=offset
    )


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, user: CurrentUser, jobs: JobServiceDep) -> JobResponse:
    return JobResponse.model_validate(await jobs.get(job_id, user.id))


@router.post("/{job_id}/retry", response_model=JobResponse)
async def retry_job(job_id: uuid.UUID, user: CurrentUser, jobs: JobServiceDep) -> JobResponse:
    return JobResponse.model_validate(await jobs.retry(job_id, user.id))
