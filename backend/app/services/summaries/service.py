"""Requesting summaries: cache by (version, model, prompt version), one job at a time."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import run_after_commit
from app.core.errors import ConflictError, ServiceUnavailableError
from app.core.logging import get_logger
from app.models.document import Chunk, Document, DocumentStatus
from app.models.job import Job
from app.models.summary import PaperSummary, SummaryStatus
from app.services.jobs import JobService
from app.services.llm import current_model, llm_status, on_free_tier, provider_name
from app.services.summaries.spec import PROMPT_VERSION

log = get_logger(__name__)
SUMMARY_JOB = "paper.summarize"
ACTIVE = (SummaryStatus.QUEUED, SummaryStatus.RUNNING)


def config_key(settings: Settings, version_id: uuid.UUID) -> str:
    return f"{version_id}:{provider_name(settings)}:{current_model(settings)}:{PROMPT_VERSION}"


async def latest_summary(session: AsyncSession, document_id: uuid.UUID) -> PaperSummary | None:
    return await session.scalar(
        select(PaperSummary)
        .where(PaperSummary.document_id == document_id)
        .order_by(PaperSummary.created_at.desc())
        .limit(1)
    )


async def last_ready_summary(session: AsyncSession, document_id: uuid.UUID) -> PaperSummary | None:
    return await session.scalar(
        select(PaperSummary)
        .where(
            PaperSummary.document_id == document_id,
            PaperSummary.status == SummaryStatus.READY,
        )
        .order_by(PaperSummary.created_at.desc())
        .limit(1)
    )


def staleness(summary: PaperSummary, document: Document, settings: Settings) -> str | None:
    """Why a summary no longer matches the paper or the configuration (None: it does)."""
    if summary.version_id != document.current_version_id:
        return "This summary was made from an earlier version of the paper."
    used = summary.generation_config or {}
    if used.get("prompt_version") and used["prompt_version"] != PROMPT_VERSION:
        return "Summaries are now written differently; regenerate to update this one."
    model = current_model(settings)
    if used.get("llm_model") and used["llm_model"] != model and used.get("llm_provider") != "fake":
        return f"This summary was written by {used['llm_model']}; the current model is {model}."
    return None


async def job_progress(session: AsyncSession, summary: PaperSummary) -> dict[str, Any] | None:
    if summary.status not in ACTIVE or summary.job_id is None:
        return None
    job = await session.get(Job, summary.job_id)
    if job is None:
        return None
    return {"stage": job.stage, "detail": job.stage_detail, "progress": job.progress}


async def _check_ready(session: AsyncSession, settings: Settings, document: Document) -> None:
    if document.status != DocumentStatus.READY or document.current_version_id is None:
        raise ConflictError("The paper must finish processing before it can be summarized.")
    passages = await session.scalar(
        select(func.count())
        .select_from(Chunk)
        .where(Chunk.version_id == document.current_version_id)
    )
    if not passages:
        if document.index_status == "failed":
            raise ConflictError(
                "This paper couldn't be indexed, so there are no passages to summarize.",
                hint="Re-run indexing from the Overview tab, then try again.",
            )
        raise ConflictError(
            "The paper is still being indexed.", hint="Try again when indexing has finished."
        )
    await ensure_llm_ready(settings)


async def ensure_llm_ready(settings: Settings) -> None:
    """Refuse before queueing work that would only fail: say what's wrong and how to fix it."""
    status = await llm_status(settings)
    if not status.get("ready"):
        raise ServiceUnavailableError(
            status.get("problem") or "The language model isn't ready.", hint=status.get("hint")
        )


async def request_summary(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    document: Document,
    *,
    force: bool = False,
) -> PaperSummary:
    """Return the cached summary, the one being written, or start a new one."""
    latest = await latest_summary(session, document.id)
    if latest is not None and latest.status in ACTIVE:
        return latest
    key = config_key(settings, document.current_version_id) if document.current_version_id else ""
    if (
        not force
        and latest is not None
        and latest.status == SummaryStatus.READY
        and latest.config_key == key
    ):
        return latest
    await _check_ready(session, settings, document)
    return await _start(session, jobs, document, key)


async def _start(
    session: AsyncSession, jobs: JobService, document: Document, key: str
) -> PaperSummary:
    assert document.current_version_id is not None
    summary = PaperSummary(
        user_id=document.user_id,
        document_id=document.id,
        version_id=document.current_version_id,
        config_key=key,
    )
    session.add(summary)
    await session.flush()
    job = await jobs.enqueue(
        document.user_id,
        SUMMARY_JOB,
        payload={"summary_id": str(summary.id)},
        subject_type="document",
        subject_id=document.id,
    )
    summary.job_id = job.id
    return summary


async def auto_summarize(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    jobs_for: Any,
    document_id: uuid.UUID,
) -> str:
    """After processing: summarize the paper if enabled and the model is ready.

    Returns what happened (for the processing job's result). Never raises: a missing
    model must not make the upload look failed — the paper page offers "Generate".
    """
    if not settings.summary_auto:
        return "disabled"
    if on_free_tier(settings):
        # Each call comes out of the user's daily allowance and sends the paper's text to the
        # model's host: only when they ask for a summary, never because they uploaded.
        return "free_tier"
    try:
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.current_version_id is None:
                return "skipped"
            key = config_key(settings, document.current_version_id)
            latest = await latest_summary(session, document.id)
            if latest is not None and (
                latest.status in ACTIVE
                or (latest.status == SummaryStatus.READY and latest.config_key == key)
            ):
                return "exists"
            try:
                await _check_ready(session, settings, document)
            except (ConflictError, ServiceUnavailableError) as exc:
                log.info("auto_summary_skipped", document_id=str(document_id), reason=exc.message)
                return (
                    "model_unavailable" if isinstance(exc, ServiceUnavailableError) else "skipped"
                )
            await _start(session, jobs_for(session), document, key)
            await session.commit()
            run_after_commit(session)  # dispatches the job
            return "queued"
    except Exception:  # never fail the upload because of the summary
        log.exception("auto_summary_failed", document_id=str(document_id))
        return "error"
