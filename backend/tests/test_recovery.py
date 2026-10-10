"""Startup recovery: jobs interrupted by a stopped server resume, or fail cleanly with their subject."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import get_session_factory
from app.demo import sample_papers as sp
from app.models.document import Document, DocumentStatus
from app.models.job import Job, JobStatus
from app.models.summary import PaperSummary, SummaryStatus
from app.workers.dispatcher import get_dispatcher
from app.workers.recovery import MAX_ATTEMPTS, recover_interrupted_jobs
from tests.test_indexing_api import upload

API = "/api/v1"


@pytest.fixture
async def lora(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> str:
    data = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return await upload(auth_client, settings, "l.pdf", data)


async def summarize(client: AsyncClient, settings: Settings, doc: str) -> dict[str, Any]:
    response = await client.post(f"{API}/documents/{doc}/summary")
    assert response.status_code == 202, response.text
    await get_dispatcher(settings).drain()
    return (await client.get(f"{API}/documents/{doc}/summary")).json()


async def interrupt(kind: str, attempts: int) -> tuple[uuid.UUID, uuid.UUID]:
    """Put the latest job of `kind` (and its summary) back in the state a killed process leaves."""
    async with get_session_factory()() as session:
        job = (
            await session.execute(
                select(Job).where(Job.kind == kind).order_by(Job.created_at.desc()).limit(1)
            )
        ).scalar_one()
        job.status, job.stage, job.progress, job.attempts = (
            JobStatus.RUNNING,
            "writing",
            0.4,
            attempts,
        )
        summary = await session.get(PaperSummary, uuid.UUID(job.payload["summary_id"]))
        assert summary is not None
        summary.status = SummaryStatus.RUNNING
        await session.commit()
        return job.id, summary.id


async def test_an_interrupted_job_resumes_on_startup(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    await summarize(auth_client, settings, lora)
    job_id, summary_id = await interrupt("paper.summarize", attempts=1)

    dispatcher = get_dispatcher(settings)
    assert await recover_interrupted_jobs(get_session_factory(), dispatcher) == {
        "resumed": 1,
        "failed": 0,
    }
    await dispatcher.drain()
    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        summary = await session.get(PaperSummary, summary_id)
        assert job is not None and summary is not None
        assert (job.status, job.attempts) == (JobStatus.SUCCEEDED, 2)
        assert summary.status == SummaryStatus.READY


async def test_a_job_interrupted_too_often_fails_with_its_subject(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    await summarize(auth_client, settings, lora)
    job_id, summary_id = await interrupt("paper.summarize", attempts=MAX_ATTEMPTS)

    result = await recover_interrupted_jobs(get_session_factory(), get_dispatcher(settings))
    assert result == {"resumed": 0, "failed": 1}
    async with get_session_factory()() as session:
        job = await session.get(Job, job_id)
        summary = await session.get(PaperSummary, summary_id)
        assert job is not None and summary is not None
        assert job.status == JobStatus.FAILED and "interrupted" in (job.error_message or "")
        assert summary.status == SummaryStatus.FAILED
        assert summary.error_message == job.error_message  # the paper page explains it
    retried = await auth_client.post(f"{API}/jobs/{job_id}/retry")
    assert retried.status_code in (200, 202), retried.text


async def test_a_document_stuck_processing_is_failed_and_queued_jobs_restart(
    auth_client: AsyncClient, settings: Settings, lora: str
) -> None:
    # A summary job that was queued but never started (lost with the process) …
    response = await auth_client.post(f"{API}/documents/{lora}/summary")
    assert response.status_code == 202
    await get_dispatcher(settings).drain()
    async with get_session_factory()() as session:
        queued = (
            await session.execute(select(Job).where(Job.kind == "paper.summarize"))
        ).scalar_one()
        queued.status, queued.attempts = JobStatus.QUEUED, 0
        # … and a paper whose processing was interrupted too often.
        job = (
            await session.execute(select(Job).where(Job.kind == "document.process"))
        ).scalar_one()
        job.status, job.attempts = JobStatus.RUNNING, MAX_ATTEMPTS
        document = await session.get(Document, uuid.UUID(lora))
        assert document is not None
        document.status = DocumentStatus.PROCESSING
        await session.commit()

    dispatcher = get_dispatcher(settings)
    assert await recover_interrupted_jobs(get_session_factory(), dispatcher) == {
        "resumed": 1,
        "failed": 1,
    }
    await dispatcher.drain()
    paper = (await auth_client.get(f"{API}/documents/{lora}")).json()
    assert paper["status"] == "failed" and "interrupted" in paper["error_message"]
    async with get_session_factory()() as session:
        assert (await session.get(Job, queued.id)).status == JobStatus.SUCCEEDED  # type: ignore[union-attr]
