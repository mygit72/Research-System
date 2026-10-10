"""Requesting, listing, editing and deleting research reports."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.models.job import Job
from app.models.report import ReportKind, ReportStatus, ResearchReport
from app.services import organization as org
from app.services.jobs import JobService
from app.services.summaries.service import ensure_llm_ready

REPORT_JOB = "report.generate"
ACTIVE = (ReportStatus.QUEUED, ReportStatus.RUNNING)
EDITABLE_KINDS = ("text", "answer", "chronology", "open")


async def request_report(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    user_id: uuid.UUID,
    kind: ReportKind,
    *,
    query: str = "",
    document_ids: list[uuid.UUID] | None = None,
    collection_id: uuid.UUID | None = None,
    depth: str = "standard",
    limits: dict[str, Any] | None = None,
) -> ResearchReport:
    query = " ".join(query.split())
    document_ids = list(dict.fromkeys(document_ids or []))
    collection_name = None
    if document_ids:
        await org.owned_documents(session, user_id, document_ids)
    if collection_id is not None:
        collection_name = (await org.get_collection(session, user_id, collection_id)).name
    if kind == ReportKind.DEEP_RESEARCH:
        if len(query.split()) < 3:
            raise ValidationError("Ask a research question of at least a few words.")
    elif kind == ReportKind.REVIEW:
        if not (query or document_ids or collection_id):
            raise ValidationError("Give a topic, choose papers, or choose a collection.")
    elif not (document_ids or collection_id or query):
        raise ValidationError("Choose papers or a collection.")
    if (
        kind != ReportKind.DEEP_RESEARCH
        and document_ids
        and len(document_ids) < 2
        and kind != ReportKind.GAPS
    ):
        raise ValidationError("Choose at least 2 papers.")
    await ensure_llm_ready(settings)

    scope = (
        f"“{collection_name}”"
        if collection_name
        else f"{len(document_ids)} papers"
        if document_ids
        else None
    )
    title = {
        ReportKind.REVIEW: query or f"Literature review of {scope}",
        ReportKind.GAPS: f"Research gaps: {query or scope}",
        ReportKind.DISAGREEMENTS: f"Potential disagreements: {query or scope}",
        ReportKind.DEEP_RESEARCH: query,
    }[kind]
    report = ResearchReport(
        user_id=user_id,
        kind=kind,
        title=title[:300],
        query=query,
        collection_id=collection_id,
        params={
            "document_ids": [str(d) for d in document_ids],
            "collection_id": str(collection_id) if collection_id else None,
            "depth": depth,
            **(limits or {}),
        },
    )
    session.add(report)
    await session.flush()
    job = await jobs.enqueue(
        user_id,
        REPORT_JOB,
        payload={"report_id": str(report.id)},
        subject_type="report",
        subject_id=report.id,
    )
    report.job_id = job.id
    return report


async def get_report(
    session: AsyncSession, user_id: uuid.UUID, report_id: uuid.UUID
) -> ResearchReport:
    report = await session.get(ResearchReport, report_id)
    if report is None or report.user_id != user_id:
        raise NotFoundError("Report not found.")
    return report


async def list_reports(
    session: AsyncSession, user_id: uuid.UUID, kind: str | None, limit: int
) -> list[ResearchReport]:
    query = select(ResearchReport).where(ResearchReport.user_id == user_id)
    if kind:
        query = query.where(ResearchReport.kind == kind)
    rows = await session.execute(query.order_by(ResearchReport.created_at.desc()).limit(limit))
    return list(rows.scalars())


async def progress(session: AsyncSession, report: ResearchReport) -> dict[str, Any] | None:
    if report.status not in ACTIVE or report.job_id is None:
        return None
    job = await session.get(Job, report.job_id)
    if job is None:
        return None
    return {"stage": job.stage, "detail": job.stage_detail, "progress": job.progress}


def apply_edits(
    report: ResearchReport, title: str | None, sections: list[dict[str, Any]] | None
) -> None:
    """User edits: the title and the text (and titles) of written sections.

    Edited text is the user's: it is marked as edited and no longer carries the automatic
    check's label (the check was of the original wording).
    """
    if report.status != ReportStatus.READY:
        raise ValidationError("A report can be edited once it's ready.")
    if title is not None:
        title = " ".join(title.split())
        if not title:
            raise ValidationError("The title can't be empty.")
        report.title = title[:300]
    if sections:
        by_key = {s["key"]: s for s in report.sections}
        updated = []
        for requested in sections:
            section = by_key.get(requested["key"])
            if section is None:
                raise ValidationError(f"There's no section “{requested['key']}”.")
            if requested.get("text") is not None and section.get("kind") not in EDITABLE_KINDS:
                raise ValidationError(
                    f"“{section['title']}” is built from data and can't be edited."
                )
        for section in report.sections:
            edit: dict[str, Any] | None = next(
                (e for e in sections if e["key"] == section["key"]), None
            )
            if edit is not None:
                section = dict(section)
                if edit.get("title"):
                    section["title"] = " ".join(edit["title"].split())[:200]
                if edit.get("text") is not None and edit["text"] != section.get("text"):
                    section["text"] = edit["text"]
                    section["edited"] = True
                    section["label"] = "Edited by you — not re-checked"
            updated.append(section)
        report.sections = updated
    report.edited_at = datetime.now(UTC)
