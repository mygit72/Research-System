"""Evaluation: datasets of questions with expected evidence, runs, comparisons."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, JobServiceDep, SettingsDep
from app.models.evaluation import EvalDataset, EvalItem, EvalRun
from app.models.job import Job
from app.schemas.evaluation import (
    DatasetCreate,
    DatasetOut,
    DatasetUpdate,
    GenerateRequest,
    ItemCreate,
    ItemOut,
    ItemUpdate,
    RunCreate,
    RunOut,
    RunSummary,
)
from app.schemas.summary import SummaryProgress
from app.services.evaluation.service import (
    dataset_counts,
    evidence_from_chunks,
    get_dataset,
    get_item,
    get_run,
    request_generation,
    request_run,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


async def _dataset_out(db: DbSession, dataset: EvalDataset) -> DatasetOut:
    await db.flush()
    await db.refresh(dataset)
    counts = (await dataset_counts(db, [dataset.id]))[dataset.id]
    return DatasetOut.model_validate(dataset).model_copy(update=counts)


@router.get("/datasets", response_model=list[DatasetOut])
async def list_datasets(user: CurrentUser, db: DbSession) -> list[DatasetOut]:
    rows = list(
        (
            await db.execute(
                select(EvalDataset)
                .where(EvalDataset.user_id == user.id)
                .order_by(EvalDataset.updated_at.desc())
            )
        ).scalars()
    )
    counts = await dataset_counts(db, [d.id for d in rows]) if rows else {}
    return [DatasetOut.model_validate(d).model_copy(update=counts[d.id]) for d in rows]


@router.post("/datasets", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def create_dataset(body: DatasetCreate, user: CurrentUser, db: DbSession) -> DatasetOut:
    dataset = EvalDataset(user_id=user.id, name=body.name.strip(), description=body.description)
    db.add(dataset)
    return await _dataset_out(db, dataset)


@router.get("/datasets/{dataset_id}", response_model=DatasetOut)
async def read_dataset(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> DatasetOut:
    return await _dataset_out(db, await get_dataset(db, user.id, dataset_id))


@router.patch("/datasets/{dataset_id}", response_model=DatasetOut)
async def update_dataset(
    dataset_id: uuid.UUID, body: DatasetUpdate, user: CurrentUser, db: DbSession
) -> DatasetOut:
    dataset = await get_dataset(db, user.id, dataset_id)
    if body.name is not None:
        dataset.name = body.name.strip()
    if body.description is not None:
        dataset.description = body.description
    return await _dataset_out(db, dataset)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_dataset(db, user.id, dataset_id))


# --- items ---------------------------------------------------------------------------------------


@router.get("/datasets/{dataset_id}/items", response_model=list[ItemOut])
async def list_items(dataset_id: uuid.UUID, user: CurrentUser, db: DbSession) -> list[ItemOut]:
    await get_dataset(db, user.id, dataset_id)
    rows = (
        await db.execute(
            select(EvalItem).where(EvalItem.dataset_id == dataset_id).order_by(EvalItem.created_at)
        )
    ).scalars()
    return [ItemOut.model_validate(i) for i in rows]


@router.post(
    "/datasets/{dataset_id}/items",
    response_model=ItemOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a question with the passages that answer it",
)
async def create_item(
    dataset_id: uuid.UUID, body: ItemCreate, user: CurrentUser, db: DbSession
) -> ItemOut:
    await get_dataset(db, user.id, dataset_id)
    item = EvalItem(
        dataset_id=dataset_id,
        user_id=user.id,
        question=body.question.strip(),
        expected=await evidence_from_chunks(db, user.id, body.chunk_ids),
        reference_answer=body.reference_answer,
        source="manual",
        status="verified",
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.patch(
    "/items/{item_id}",
    response_model=ItemOut,
    summary="Edit a question, its evidence, or accept a generated one",
)
async def update_item(
    item_id: uuid.UUID, body: ItemUpdate, user: CurrentUser, db: DbSession
) -> ItemOut:
    item = await get_item(db, user.id, item_id)
    if body.question is not None:
        item.question = body.question.strip()
    if body.chunk_ids is not None:
        item.expected = await evidence_from_chunks(db, user.id, body.chunk_ids)
    if body.reference_answer is not None:
        item.reference_answer = body.reference_answer
    if body.status is not None:
        item.status = body.status
    await db.flush()
    await db.refresh(item)
    return ItemOut.model_validate(item)


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_item(db, user.id, item_id))


@router.post(
    "/datasets/{dataset_id}/generate",
    response_model=DatasetOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Write candidate questions from passages (to be checked before they count)",
)
async def generate(
    dataset_id: uuid.UUID,
    body: GenerateRequest,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> DatasetOut:
    dataset = await get_dataset(db, user.id, dataset_id)
    await request_generation(db, settings, jobs, dataset, body.count, body.document_ids)
    return await _dataset_out(db, dataset)


# --- runs ----------------------------------------------------------------------------------------


async def _run_out(db: DbSession, run: EvalRun) -> RunOut:
    out = RunOut.model_validate(run)
    if run.status in ("queued", "running") and run.job_id:
        job = await db.get(Job, run.job_id)
        if job is not None:
            out.progress = SummaryProgress(
                stage=job.stage, detail=job.stage_detail, progress=job.progress
            )
    return out


@router.post(
    "/datasets/{dataset_id}/runs",
    response_model=RunOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Measure a configuration on the dataset's verified questions",
    description="`kind`: retrieval (fast: Recall@K, Precision@K, MRR, nDCG) or rag (answers "
    "each question: also faithfulness, citation correctness, context recall / precision, "
    "answer relevance; at most 25 questions).",
)
async def create_run(
    dataset_id: uuid.UUID,
    body: RunCreate,
    user: CurrentUser,
    db: DbSession,
    settings: SettingsDep,
    jobs: JobServiceDep,
) -> RunOut:
    dataset = await get_dataset(db, user.id, dataset_id)
    run = await request_run(
        db, settings, jobs, dataset, body.name, body.kind, body.config.model_dump(exclude_none=True)
    )
    await db.flush()
    await db.refresh(run)
    return await _run_out(db, run)


@router.get("/runs", response_model=list[RunSummary])
async def list_runs(
    user: CurrentUser,
    db: DbSession,
    dataset_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[RunSummary]:
    query = select(EvalRun).where(EvalRun.user_id == user.id)
    if dataset_id:
        query = query.where(EvalRun.dataset_id == dataset_id)
    rows = (await db.execute(query.order_by(EvalRun.created_at.desc()).limit(limit))).scalars()
    return [RunSummary.model_validate(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
async def read_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> RunOut:
    return await _run_out(db, await get_run(db, user.id, run_id))


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await get_run(db, user.id, run_id))
