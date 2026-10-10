"""Background job system: enqueue-after-commit, progress, success, failure, retry."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter
from httpx import AsyncClient

from app.api.deps import CurrentUser, JobServiceDep
from app.core.config import Settings
from app.workers.dispatcher import get_dispatcher
from app.workers.registry import JobContext, JobFailedError, job_handler

attempts: dict[str, int] = {}


@job_handler("test.echo")
async def echo_handler(ctx: JobContext) -> dict[str, Any]:
    await ctx.report("working", 0.5)
    await ctx.report("working", 0.2)  # progress must never go backwards
    return {"echo": ctx.payload["value"]}


@job_handler("test.flaky")
async def flaky_handler(ctx: JobContext) -> dict[str, Any]:
    key = str(ctx.job_id)
    attempts[key] = attempts.get(key, 0) + 1
    if attempts[key] == 1:
        raise JobFailedError("The file looks corrupted.", detail="bad xref table")
    return {"ok": True}


@job_handler("test.crash")
async def crash_handler(ctx: JobContext) -> dict[str, Any]:
    raise RuntimeError("secret internal detail")


def _mount_enqueue_route(app: Any) -> None:
    router = APIRouter()

    @router.post("/test/jobs/{kind}")
    async def enqueue(kind: str, user: CurrentUser, jobs: JobServiceDep) -> dict[str, str]:
        job = await jobs.enqueue(user.id, kind, payload={"value": 42})
        return {"id": str(job.id)}

    app.include_router(router)


async def _run(auth_client: AsyncClient, app: Any, settings: Settings, kind: str) -> dict[str, Any]:
    _mount_enqueue_route(app)
    job_id = (await auth_client.post(f"/test/jobs/{kind}")).json()["id"]
    await get_dispatcher(settings).drain()
    response = await auth_client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    return dict(response.json())


async def test_job_succeeds(auth_client: AsyncClient, app: Any, settings: Settings) -> None:
    job = await _run(auth_client, app, settings, "test.echo")
    assert job["status"] == "succeeded"
    assert job["progress"] == 1.0
    assert job["result"] == {"echo": 42}
    assert job["attempts"] == 1


async def test_job_failure_is_user_safe(
    auth_client: AsyncClient, app: Any, settings: Settings
) -> None:
    job = await _run(auth_client, app, settings, "test.crash")
    assert job["status"] == "failed"
    assert job["error_message"] == "Something went wrong while processing this task."
    assert "secret internal detail" not in str(job)


async def test_job_retry(auth_client: AsyncClient, app: Any, settings: Settings) -> None:
    job = await _run(auth_client, app, settings, "test.flaky")
    assert job["status"] == "failed"
    assert job["error_message"] == "The file looks corrupted."

    retried = await auth_client.post(f"/api/v1/jobs/{job['id']}/retry")
    assert retried.json()["status"] == "queued"
    await get_dispatcher(settings).drain()
    final = (await auth_client.get(f"/api/v1/jobs/{job['id']}")).json()
    assert final["status"] == "succeeded"
    assert final["attempts"] == 2


async def test_jobs_are_private(auth_client: AsyncClient, app: Any, settings: Settings) -> None:
    job = await _run(auth_client, app, settings, "test.echo")
    listing = (await auth_client.get("/api/v1/jobs")).json()
    assert listing["total"] == 1

    other = await auth_client.post(
        "/api/v1/auth/register",
        json={"email": "other@example.com", "password": "correct-horse-42"},
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    assert (await auth_client.get(f"/api/v1/jobs/{job['id']}", headers=headers)).status_code == 404
    assert (await auth_client.get(f"/api/v1/jobs/{uuid.uuid4()}")).status_code == 404
