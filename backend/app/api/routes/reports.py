"""Literature reviews, research gaps, disagreements and deep research (all are reports)."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.models.report import ReportKind, ResearchReport
from app.schemas.report import (
    DeepResearchCreate,
    PapersAnalysisCreate,
    ReportOut,
    ReportSummary,
    ReportUpdate,
    ReviewCreate,
)
from app.schemas.summary import SummaryProgress
from app.services.analysis import export
from app.services.analysis.service import (
    apply_edits,
    get_report,
    list_reports,
    progress,
    request_report,
)

router = APIRouter(tags=["reports"])


async def _out(db: DbSession, report: ResearchReport) -> ReportOut:
    out = ReportOut.model_validate(report)
    state = await progress(db, report)
    out.progress = SummaryProgress(**state) if state else None
    out.error_hint = (report.trace or {}).get("error_hint")
    return out


async def _created(db: DbSession, report: ResearchReport) -> ReportOut:
    await db.flush()
    await db.refresh(report)
    return await _out(db, report)


@router.post(
    "/literature-review",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Write a structured, cited literature review",
    description="Papers come from `document_ids`, a `collection_id`, or a search for `topic` "
    "(the topic also frames the writing). Runs as a `report.generate` job: find papers → "
    "read (summaries, written if missing) → group by approach → compare → disagreements → "
    "gaps → write → verify every sentence.",
)
async def create_review(
    body: ReviewCreate, user: CurrentUser, db: DbSession, settings: SettingsDep, jobs: JobServiceDep
) -> ReportOut:
    report = await request_report(
        db, settings, jobs, user.id, ReportKind.REVIEW,
        query=body.topic, document_ids=body.document_ids,
        collection_id=body.collection_id, depth=body.depth,
    )  # fmt: skip
    return await _created(db, report)


@router.post(
    "/research-gaps",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Find research gaps, labelled as stated by the authors or system-generated",
)
async def create_gaps(
    body: PapersAnalysisCreate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> ReportOut:
    report = await request_report(
        db, settings, jobs, user.id, ReportKind.GAPS,
        query=body.topic, document_ids=body.document_ids,
        collection_id=body.collection_id, depth=body.depth,
    )  # fmt: skip
    return await _created(db, report)


@router.post(
    "/contradictions",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Flag potential disagreements between papers (never says which is right)",
)
async def create_disagreements(
    body: PapersAnalysisCreate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> ReportOut:
    report = await request_report(
        db, settings, jobs, user.id, ReportKind.DISAGREEMENTS,
        query=body.topic, document_ids=body.document_ids,
        collection_id=body.collection_id, depth=body.depth,
    )  # fmt: skip
    return await _created(db, report)


@router.post(
    "/deep-research",
    response_model=ReportOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Multi-step research over your papers with step, token and time limits",
)
async def create_deep_research(
    body: DeepResearchCreate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> ReportOut:
    report = await request_report(
        db, settings, jobs, user.id, ReportKind.DEEP_RESEARCH,
        query=body.question, document_ids=body.document_ids, collection_id=body.collection_id,
        limits={
            "max_steps": body.max_steps,
            "token_budget": body.token_budget,
            "timeout_seconds": body.timeout_seconds,
        },
    )  # fmt: skip
    return await _created(db, report)


@router.get("/reports", response_model=list[ReportSummary], summary="Your reports, newest first")
async def recent_reports(
    user: CurrentUser,
    db: DbSession,
    kind: Literal["review", "gaps", "disagreements", "deep_research"] | None = None,
    limit: int = Query(default=30, ge=1, le=100),
) -> list[ReportSummary]:
    return [ReportSummary.model_validate(r) for r in await list_reports(db, user.id, kind, limit)]


@router.get("/reports/{report_id}", response_model=ReportOut)
async def read_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ReportOut:
    return await _out(db, await get_report(db, user.id, report_id))


@router.patch(
    "/reports/{report_id}",
    response_model=ReportOut,
    summary="Edit the title or the text of written sections",
)
async def update_report(
    report_id: uuid.UUID, body: ReportUpdate, user: CurrentUser, db: DbSession
) -> ReportOut:
    report = await get_report(db, user.id, report_id)
    apply_edits(
        report,
        body.title,
        [s.model_dump(exclude_none=True) for s in body.sections] if body.sections else None,
    )
    await db.flush()
    await db.refresh(report)
    return await _out(db, report)


@router.delete("/reports/{report_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_report(report_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_report(db, user.id, report_id))


MEDIA = {
    "md": "text/markdown; charset=utf-8",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


@router.get("/reports/{report_id}/export", summary="Download as Markdown, Word or PDF")
async def export_report(
    report_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    format: Literal["md", "docx", "pdf"] = "md",
) -> Response:
    report = await get_report(db, user.id, report_id)
    if format == "md":
        content: bytes = export.to_markdown(report).encode()
    elif format == "docx":
        content = export.to_docx(report)
    else:
        content = export.to_pdf(report)
    return Response(
        content,
        media_type=MEDIA[format],
        headers={
            "Content-Disposition": f'attachment; filename="{export.filename(report, format)}"'
        },
    )
