from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep, JobServiceDep, SettingsDep
from app.core.config import Settings
from app.models.document import Document
from app.models.summary import PaperSummary, SummaryStatus
from app.schemas.summary import SummaryOut, SummaryProgress, SummaryRequest
from app.services.summaries import (
    job_progress,
    last_ready_summary,
    latest_summary,
    request_summary,
    staleness,
)

router = APIRouter(prefix="/documents", tags=["summaries"])


async def _out(
    db: DbSession, summary: PaperSummary, document: Document, settings: Settings
) -> SummaryOut:
    out = SummaryOut.model_validate(summary)
    out.error_hint = (summary.trace or {}).get("error_hint")
    progress = await job_progress(db, summary)
    out.progress = SummaryProgress(**progress) if progress else None
    out.stale = staleness(summary, document, settings) if summary.status == "ready" else None
    out.trace = {k: v for k, v in (summary.trace or {}).items() if k != "error_hint"}
    if summary.status != SummaryStatus.READY:
        # While a new summary is written (or after it failed), the last good one is still
        # shown; it is only replaced once the new one is ready.
        previous = await last_ready_summary(db, summary.document_id)
        if previous is not None:
            out.previous = await _out(db, previous, document, settings)
    return out


@router.get(
    "/{document_id}/summary",
    response_model=SummaryOut | None,
    summary="The paper's structured summary (null if none has been generated)",
)
async def get_summary(
    document_id: uuid.UUID,
    user: CurrentUser,
    documents: DocumentServiceDep,
    db: DbSession,
    settings: SettingsDep,
) -> SummaryOut | None:
    document = await documents.get(user.id, document_id)
    summary = await latest_summary(db, document.id)
    return await _out(db, summary, document, settings) if summary else None


@router.post(
    "/{document_id}/summary",
    response_model=SummaryOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate the summary (returns the cached one when nothing changed)",
    description="Summaries are cached by (paper version, model, prompt version). "
    "`force` writes a new one; until it is ready the previous one is returned as `previous`.",
)
async def generate_summary(
    document_id: uuid.UUID,
    user: CurrentUser,
    documents: DocumentServiceDep,
    jobs: JobServiceDep,
    db: DbSession,
    settings: SettingsDep,
    body: SummaryRequest | None = None,
) -> SummaryOut:
    document = await documents.get(user.id, document_id)
    summary = await request_summary(db, settings, jobs, document, force=bool(body and body.force))
    await db.flush()
    await db.refresh(summary)
    return await _out(db, summary, document, settings)
