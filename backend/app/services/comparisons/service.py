"""Starting, listing and reading comparisons."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.comparison import Comparison, ComparisonStatus
from app.models.document import Chunk, Document, DocumentStatus
from app.models.job import Job
from app.services.comparisons.generate import short_title
from app.services.comparisons.spec import MAX_PAPERS, MIN_PAPERS, PROMPT_VERSION, ComparisonKind
from app.services.jobs import JobService
from app.services.llm import current_model, provider_name
from app.services.summaries.service import ensure_llm_ready

COMPARISON_JOB = "comparison.generate"
ACTIVE = (ComparisonStatus.QUEUED, ComparisonStatus.RUNNING)


def config_key(settings: Settings, kind: str, documents: list[Document]) -> str:
    """Same papers (any order), same versions, kind, model and prompt → same comparison."""
    papers = ",".join(sorted(f"{d.id}@{d.current_version_id}" for d in documents))
    return f"{kind}:{provider_name(settings)}:{current_model(settings)}:{PROMPT_VERSION}:{papers}"


def comparison_title(kind: str, documents: list[Document]) -> str:
    title = " vs ".join(short_title(d.title, 40) for d in documents)
    return (f"Methodology: {title}" if kind == ComparisonKind.METHODOLOGY else title)[:500]


async def _papers(
    session: AsyncSession, user_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> list[Document]:
    if len(set(document_ids)) != len(document_ids):
        raise ValidationError("Each paper can only be compared once.")
    if not MIN_PAPERS <= len(document_ids) <= MAX_PAPERS:
        raise ValidationError(f"Choose between {MIN_PAPERS} and {MAX_PAPERS} papers to compare.")
    found = {
        d.id: d
        for d in (
            await session.execute(
                select(Document).where(Document.id.in_(document_ids), Document.user_id == user_id)
            )
        ).scalars()
    }
    if len(found) != len(document_ids):
        raise NotFoundError("One of these papers doesn't exist.")
    documents = [found[d] for d in document_ids]  # keep the user's column order
    for document in documents:
        if document.status != DocumentStatus.READY or document.current_version_id is None:
            raise ConflictError(f"“{document.title}” hasn't finished processing yet.")
        passages = await session.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.version_id == document.current_version_id)
        )
        if not passages:
            raise ConflictError(
                f"“{document.title}” isn't indexed yet, so it can't be compared.",
                hint="Wait for indexing to finish, or re-run indexing from its Overview tab.",
            )
    return documents


async def request_comparison(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    kind: ComparisonKind,
    *,
    force: bool = False,
) -> Comparison:
    """The existing comparison of these papers (ready or being written), or a new one."""
    documents = await _papers(session, user_id, document_ids)
    key = config_key(settings, kind, documents)
    existing = await session.scalar(
        select(Comparison)
        .where(Comparison.user_id == user_id, Comparison.config_key == key)
        .order_by(Comparison.created_at.desc())
        .limit(1)
    )
    if existing is not None and (
        existing.status in ACTIVE or (existing.status == ComparisonStatus.READY and not force)
    ):
        return existing
    await ensure_llm_ready(settings)
    comparison = Comparison(
        user_id=user_id,
        title=comparison_title(kind, documents),
        kind=kind.value,
        document_ids=[str(d.id) for d in documents],
        config_key=key,
        columns=[
            {
                "document_id": str(d.id),
                "version_id": str(d.current_version_id),
                "letter": chr(ord("A") + i),
                "title": d.title,
                "year": d.year,
                "authors_display": d.authors_display,
            }
            for i, d in enumerate(documents)
        ],
    )
    session.add(comparison)
    await session.flush()
    job = await jobs.enqueue(user_id, COMPARISON_JOB, payload={"comparison_id": str(comparison.id)})
    comparison.job_id = job.id
    return comparison


async def get_comparison(
    session: AsyncSession, user_id: uuid.UUID, comparison_id: uuid.UUID
) -> Comparison:
    comparison = await session.get(Comparison, comparison_id)
    if comparison is None or comparison.user_id != user_id:
        raise NotFoundError("Comparison not found.")
    return comparison


async def list_comparisons(
    session: AsyncSession, user_id: uuid.UUID, limit: int, document_id: uuid.UUID | None = None
) -> list[Comparison]:
    query = select(Comparison).where(Comparison.user_id == user_id)
    rows = list(
        (await session.execute(query.order_by(Comparison.created_at.desc()).limit(200))).scalars()
    )
    if document_id is not None:  # JSON containment differs per database; lists are short
        rows = [c for c in rows if str(document_id) in c.document_ids]
    return rows[:limit]


async def progress(session: AsyncSession, comparison: Comparison) -> dict[str, Any] | None:
    if comparison.status not in ACTIVE or comparison.job_id is None:
        return None
    job = await session.get(Job, comparison.job_id)
    if job is None:
        return None
    return {"stage": job.stage, "detail": job.stage_detail, "progress": job.progress}


async def paper_states(
    session: AsyncSession, settings: Settings, comparison: Comparison
) -> tuple[set[str], str | None]:
    """Papers deleted since, and why the comparison is out of date (None: it isn't)."""
    ids = [uuid.UUID(c["document_id"]) for c in comparison.columns]
    documents = {
        str(d.id): d
        for d in (await session.execute(select(Document).where(Document.id.in_(ids)))).scalars()
    }
    deleted = {c["document_id"] for c in comparison.columns if c["document_id"] not in documents}
    if deleted:
        return deleted, "A paper in this comparison was deleted."
    for column in comparison.columns:
        document = documents[column["document_id"]]
        if str(document.current_version_id) != column["version_id"]:
            return deleted, f"“{document.title}” has a newer version than the one compared."
    used = comparison.generation_config or {}
    if used.get("prompt_version") and used["prompt_version"] != PROMPT_VERSION:
        return deleted, "Comparisons are now written differently; regenerate to update this one."
    model = used.get("llm_model")
    if model and used.get("llm_provider") != "fake" and model != current_model(settings):
        return deleted, f"Written by {model}; the current model is {current_model(settings)}."
    return deleted, None
