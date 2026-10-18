"""Research Watches: an autonomous agent that searches arXiv for new papers on a saved topic."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep, JobServiceDep, SettingsDep
from app.schemas.agent import DigestEntryOut, RunOut, WatchCreate, WatchOut, WatchUpdate
from app.schemas.common import Page
from app.services.agent import service as agent

router = APIRouter(prefix="/watches", tags=["watches"])


async def _out(db: DbSession, watch: object) -> WatchOut:
    out = WatchOut.model_validate(watch)
    latest = await agent.latest_run(db, out.id)
    out.latest_run = RunOut.model_validate(latest) if latest else None
    return out


@router.post("", response_model=WatchOut, status_code=status.HTTP_201_CREATED)
async def create_watch(
    body: WatchCreate, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> WatchOut:
    watch = await agent.create_watch(
        db,
        settings,
        user.id,
        name=body.name,
        query=body.query,
        collection_id=body.collection_id,
        project_id=body.project_id,
        interval_hours=body.interval_hours,
        relevance_threshold=body.relevance_threshold,
        auto_import=body.auto_import,
        synthesize=body.synthesize,
        is_public=body.is_public,
    )
    return await _out(db, watch)


@router.get("", response_model=list[WatchOut])
async def list_watches(user: CurrentUser, db: DbSession) -> list[WatchOut]:
    watches = await agent.list_watches(db, user.id)
    return [await _out(db, watch) for watch in watches]


@router.get("/{watch_id}", response_model=WatchOut)
async def get_watch(watch_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WatchOut:
    return await _out(db, await agent.get_watch(db, user.id, watch_id))


@router.patch("/{watch_id}", response_model=WatchOut)
async def update_watch(
    watch_id: uuid.UUID, body: WatchUpdate, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> WatchOut:
    watch = await agent.update_watch(
        db, settings, user.id, watch_id, body.model_dump(exclude_unset=True)
    )
    return await _out(db, watch)


@router.delete("/{watch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watch(watch_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await agent.delete_watch(db, user.id, watch_id)


@router.post("/{watch_id}/run", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED)
async def run_watch_now(
    watch_id: uuid.UUID, user: CurrentUser, db: DbSession, jobs: JobServiceDep
) -> RunOut:
    watch = await agent.get_watch(db, user.id, watch_id)
    run = await agent.request_run(db, jobs, user.id, watch)
    return RunOut.model_validate(run)


@router.get("/{watch_id}/runs", response_model=Page[RunOut])
async def list_watch_runs(
    watch_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[RunOut]:
    runs, total = await agent.list_runs(db, user.id, watch_id, limit=limit, offset=offset)
    return Page(
        items=[RunOut.model_validate(r) for r in runs], total=total, limit=limit, offset=offset
    )


@router.get("/{watch_id}/digest", response_model=Page[DigestEntryOut])
async def list_watch_digest(
    watch_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Page[DigestEntryOut]:
    entries, total = await agent.list_digest(db, user.id, watch_id, limit=limit, offset=offset)
    return Page(
        items=[DigestEntryOut.model_validate(e) for e in entries],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/{watch_id}/digest/{entry_id}/import", response_model=DigestEntryOut)
async def import_digest_entry(
    watch_id: uuid.UUID,
    entry_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    documents: DocumentServiceDep,
) -> DigestEntryOut:
    await agent.get_watch(db, user.id, watch_id)  # 404s before touching an entry of another watch
    entry = await agent.import_digest_entry(db, documents, user.id, entry_id)
    return DigestEntryOut.model_validate(entry)
