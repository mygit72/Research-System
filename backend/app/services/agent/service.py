"""Research Watches: CRUD, requesting a run, and turning a digest entry into a library paper.

Run orchestration itself (search → score → import → notify) lives in `runner.py`, which runs
outside a request (a scheduled tick or a job), so it has to commit and dispatch jobs itself.
Everything in this module is request-scoped: FastAPI's `DbSession` dependency commits and
dispatches after the route returns, so nothing here calls `run_after_commit`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.models.agent import (
    AgentDigestEntry,
    AgentRun,
    AgentWatch,
    ImportStatus,
    RunStatus,
    RunTrigger,
    WatchStatus,
)
from app.models.document import DocumentMetadata, DocumentVersion
from app.services import organization as org
from app.services.agent import WATCH_RUN_JOB
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.projects.service import get_project


async def document_id_for_arxiv_id(
    session: AsyncSession, user_id: uuid.UUID, arxiv_id: str
) -> uuid.UUID | None:
    return await session.scalar(
        select(DocumentVersion.document_id)
        .join(DocumentMetadata, DocumentMetadata.version_id == DocumentVersion.id)
        .where(DocumentMetadata.user_id == user_id, DocumentMetadata.arxiv_id == arxiv_id)
    )


async def get_watch(session: AsyncSession, user_id: uuid.UUID, watch_id: uuid.UUID) -> AgentWatch:
    watch = await session.get(AgentWatch, watch_id)
    if watch is None or watch.user_id != user_id:
        raise NotFoundError("Watch not found.")
    return watch


async def list_watches(session: AsyncSession, user_id: uuid.UUID) -> list[AgentWatch]:
    rows = await session.execute(
        select(AgentWatch)
        .where(AgentWatch.user_id == user_id)
        .order_by(AgentWatch.updated_at.desc())
    )
    return list(rows.scalars())


async def _validate_links(
    session: AsyncSession,
    user_id: uuid.UUID,
    collection_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
) -> None:
    if collection_id is not None:
        await org.get_collection(session, user_id, collection_id)
    if project_id is not None:
        await get_project(session, user_id, project_id)


async def _active_watch_count(session: AsyncSession, user_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count()).where(
                AgentWatch.user_id == user_id, AgentWatch.status == WatchStatus.ACTIVE
            )
        )
        or 0
    )


async def create_watch(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    name: str,
    query: str,
    collection_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    interval_hours: int | None = None,
    relevance_threshold: float | None = None,
    auto_import: bool = False,
    synthesize: bool = False,
    is_public: bool = False,
) -> AgentWatch:
    if await _active_watch_count(session, user_id) >= settings.agent_watch_max_active_per_user:
        raise ConflictError(
            f"You can have up to {settings.agent_watch_max_active_per_user} active watches.",
            hint="Pause or delete one before creating another.",
        )
    hours = interval_hours or settings.agent_watch_default_interval_hours
    if hours < settings.agent_watch_min_interval_hours:
        raise ValidationError(
            f"The interval must be at least {settings.agent_watch_min_interval_hours} hours."
        )
    await _validate_links(session, user_id, collection_id, project_id)
    watch = AgentWatch(
        user_id=user_id,
        name=name.strip(),
        query=query.strip(),
        collection_id=collection_id,
        project_id=project_id,
        interval_hours=hours,
        relevance_threshold=(
            relevance_threshold
            if relevance_threshold is not None
            else settings.agent_watch_default_relevance_threshold
        ),
        auto_import=auto_import,
        synthesize=synthesize,
        is_public=is_public,
    )
    session.add(watch)
    await session.flush()
    return watch


async def update_watch(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    watch_id: uuid.UUID,
    changes: dict[str, Any],
) -> AgentWatch:
    watch = await get_watch(session, user_id, watch_id)
    if changes.get("interval_hours") is not None:
        hours = changes["interval_hours"]
        if not isinstance(hours, int) or hours < settings.agent_watch_min_interval_hours:
            raise ValidationError(
                f"The interval must be at least {settings.agent_watch_min_interval_hours} hours."
            )
    if "collection_id" in changes or "project_id" in changes:
        await _validate_links(
            session,
            user_id,
            changes.get("collection_id", watch.collection_id),
            changes.get("project_id", watch.project_id),
        )
    for field, value in changes.items():
        if value is not None or field in ("collection_id", "project_id"):
            setattr(watch, field, value)
    return watch


async def delete_watch(session: AsyncSession, user_id: uuid.UUID, watch_id: uuid.UUID) -> None:
    watch = await get_watch(session, user_id, watch_id)
    await session.delete(watch)


async def list_runs(
    session: AsyncSession,
    user_id: uuid.UUID,
    watch_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AgentRun], int]:
    await get_watch(session, user_id, watch_id)
    query = select(AgentRun).where(AgentRun.watch_id == watch_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(AgentRun.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def latest_run(session: AsyncSession, watch_id: uuid.UUID) -> AgentRun | None:
    return await session.scalar(
        select(AgentRun)
        .where(AgentRun.watch_id == watch_id)
        .order_by(AgentRun.created_at.desc())
        .limit(1)
    )


async def list_digest(
    session: AsyncSession,
    user_id: uuid.UUID,
    watch_id: uuid.UUID,
    *,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AgentDigestEntry], int]:
    await get_watch(session, user_id, watch_id)
    query = select(AgentDigestEntry).where(AgentDigestEntry.watch_id == watch_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(AgentDigestEntry.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def request_run(
    session: AsyncSession, jobs: JobService, user_id: uuid.UUID, watch: AgentWatch
) -> AgentRun:
    in_flight = await session.scalar(
        select(AgentRun.id).where(
            AgentRun.watch_id == watch.id,
            AgentRun.status.in_((RunStatus.QUEUED, RunStatus.RUNNING)),
        )
    )
    if in_flight is not None:
        raise ConflictError("This watch already has a run in progress.")
    run = AgentRun(
        watch_id=watch.id, user_id=user_id, status=RunStatus.QUEUED, trigger=RunTrigger.MANUAL
    )
    session.add(run)
    await session.flush()
    await jobs.enqueue(
        user_id,
        WATCH_RUN_JOB,
        payload={"watch_id": str(watch.id), "run_id": str(run.id)},
        subject_type="agent_run",
        subject_id=run.id,
    )
    return run


async def import_digest_entry(
    session: AsyncSession, documents: DocumentService, user_id: uuid.UUID, entry_id: uuid.UUID
) -> AgentDigestEntry:
    entry = await session.get(AgentDigestEntry, entry_id)
    if entry is None:
        raise NotFoundError("Digest entry not found.")
    watch = await get_watch(session, user_id, entry.watch_id)  # raises if not the user's
    if entry.import_status != ImportStatus.PENDING:
        raise ConflictError("This paper has already been handled.")
    try:
        document = await documents.import_arxiv(user_id, entry.arxiv_id)
    except ConflictError:
        existing_id = await document_id_for_arxiv_id(session, user_id, entry.arxiv_id)
        entry.import_status = ImportStatus.ALREADY_IN_LIBRARY
        entry.document_id = existing_id
        return entry
    entry.document_id = document.id
    entry.import_status = ImportStatus.IMPORTED
    if watch.collection_id is not None:
        collection = await org.get_collection(session, user_id, watch.collection_id)
        await org.add_to_collection(session, user_id, collection, [document.id])
    return entry


# --- Public (no login): a watch explicitly marked is_public ------------------------------------


async def get_public_watch(session: AsyncSession, watch_id: uuid.UUID) -> AgentWatch:
    watch = await session.get(AgentWatch, watch_id)
    if watch is None or not watch.is_public:
        raise NotFoundError("Watch not found.")
    return watch


async def list_public_digest(
    session: AsyncSession, watch_id: uuid.UUID, *, limit: int = 20, offset: int = 0
) -> tuple[list[AgentDigestEntry], int]:
    await get_public_watch(session, watch_id)  # 404s unless public; raises before any query
    query = select(AgentDigestEntry).where(AgentDigestEntry.watch_id == watch_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(AgentDigestEntry.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)
