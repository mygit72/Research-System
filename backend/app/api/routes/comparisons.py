from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.core.config import Settings
from app.models.comparison import Comparison
from app.schemas.comparison import ComparisonCreate, ComparisonOut, ComparisonSummary
from app.schemas.summary import SummaryProgress
from app.services.comparisons import (
    get_comparison,
    list_comparisons,
    paper_states,
    progress,
    request_comparison,
)

router = APIRouter(prefix="/comparisons", tags=["comparisons"])


async def _out(db: DbSession, comparison: Comparison, settings: Settings) -> ComparisonOut:
    out = ComparisonOut.model_validate(comparison)
    out.error_hint = (comparison.trace or {}).get("error_hint")
    out.trace = {k: v for k, v in (comparison.trace or {}).items() if k != "error_hint"}
    state = await progress(db, comparison)
    out.progress = SummaryProgress(**state) if state else None
    deleted, stale = await paper_states(db, settings, comparison)
    out.stale = stale if comparison.status == "ready" else None
    for column in out.columns:
        column.deleted = str(column.document_id) in deleted
    for source in out.sources:  # a deleted paper's passages stay readable, without a link
        if source.get("document", {}).get("id") in deleted:
            source["document"] = source["document"] | {"id": None}
    return out


@router.post(
    "",
    response_model=ComparisonOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Compare 2 to 5 papers (returns the existing comparison when nothing changed)",
    description="Each paper's cells are extracted once per (version, kind, model, prompt "
    "version) and reused by later comparisons. `kind`: papers | methodology.",
)
async def create_comparison(
    body: ComparisonCreate,
    user: CurrentUser,
    jobs: JobServiceDep,
    db: DbSession,
    settings: SettingsDep,
) -> ComparisonOut:
    comparison = await request_comparison(
        db, settings, jobs, user.id, body.document_ids, body.kind, force=body.force
    )
    await db.flush()
    await db.refresh(comparison)
    return await _out(db, comparison, settings)


@router.get("", response_model=list[ComparisonSummary], summary="Recent comparisons")
async def recent_comparisons(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    document_id: uuid.UUID | None = Query(default=None, description="Only those with this paper"),
) -> list[ComparisonSummary]:
    rows = await list_comparisons(db, user.id, limit, document_id)
    return [ComparisonSummary.model_validate(c) for c in rows]


@router.get("/{comparison_id}", response_model=ComparisonOut)
async def read_comparison(
    comparison_id: uuid.UUID, user: CurrentUser, db: DbSession, settings: SettingsDep
) -> ComparisonOut:
    return await _out(db, await get_comparison(db, user.id, comparison_id), settings)


@router.delete("/{comparison_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comparison(comparison_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_comparison(db, user.id, comparison_id))
