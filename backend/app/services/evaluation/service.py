"""Evaluation datasets, items and runs: creating, generating questions, listing."""

from __future__ import annotations

import random
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import NotFoundError, ValidationError
from app.models.document import Chunk, Document, DocumentStatus
from app.models.evaluation import EvalDataset, EvalItem, EvalRun
from app.services.jobs import JobService
from app.services.llm import GenerationParams, Message, get_llm
from app.services.summaries.engine import complete
from app.services.summaries.service import ensure_llm_ready

RUN_JOB = "eval.run"
GENERATE_JOB = "eval.generate"
MAX_GENERATED = 30
SKIP_SECTIONS = ("references", "acknowledgments", "preamble")

GENERATION_SYSTEM = """You write evaluation questions for a search system over research papers. Given one passage, write one specific question that this passage answers.

Rules:
- The question must be answerable from the passage alone and should need its details (a method, a dataset, a number, a finding).
- Do not copy a sentence from the passage, and do not mention "the passage" or "the text".
- Answer with the question only, on one line, ending with a question mark."""

Report = Callable[[str, float, str | None], Awaitable[None]]


async def get_dataset(
    session: AsyncSession, user_id: uuid.UUID, dataset_id: uuid.UUID
) -> EvalDataset:
    dataset = await session.get(EvalDataset, dataset_id)
    if dataset is None or dataset.user_id != user_id:
        raise NotFoundError("Evaluation dataset not found.")
    return dataset


async def get_item(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> EvalItem:
    item = await session.get(EvalItem, item_id)
    if item is None or item.user_id != user_id:
        raise NotFoundError("Question not found.")
    return item


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> EvalRun:
    run = await session.get(EvalRun, run_id)
    if run is None or run.user_id != user_id:
        raise NotFoundError("Evaluation run not found.")
    return run


async def dataset_counts(
    session: AsyncSession, dataset_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    rows = await session.execute(
        select(EvalItem.dataset_id, EvalItem.status, func.count())
        .where(EvalItem.dataset_id.in_(dataset_ids))
        .group_by(EvalItem.dataset_id, EvalItem.status)
    )
    out: dict[uuid.UUID, dict[str, int]] = {
        d: {"verified": 0, "unverified": 0} for d in dataset_ids
    }
    for dataset_id, status, count in rows.all():
        out[dataset_id][status] = count
    runs = await session.execute(
        select(EvalRun.dataset_id, func.count())
        .where(EvalRun.dataset_id.in_(dataset_ids))
        .group_by(EvalRun.dataset_id)
    )
    for dataset_id, count in runs.all():
        out[dataset_id]["runs"] = count
    return out


async def evidence_from_chunks(
    session: AsyncSession, user_id: uuid.UUID, chunk_ids: list[uuid.UUID]
) -> list[dict[str, Any]]:
    """Expected evidence from passages the user picked (search results / chunks)."""
    if not chunk_ids:
        return []
    rows = (
        await session.execute(
            select(Chunk, Document.title)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.id.in_(chunk_ids), Chunk.user_id == user_id)
        )
    ).all()
    if len(rows) != len(set(chunk_ids)):
        raise ValidationError(
            "Some of these passages don't exist (the paper may have been reprocessed)."
        )
    return [
        {
            "document_id": str(chunk.document_id),
            "version_id": str(chunk.version_id),
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "page": chunk.page_start,
            "quote": chunk.text[:600],
            "title": title,
        }
        for chunk, title in rows
    ]


async def request_run(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    dataset: EvalDataset,
    name: str,
    kind: str,
    config: dict[str, Any],
) -> EvalRun:
    verified = await session.scalar(
        select(func.count())
        .select_from(EvalItem)
        .where(EvalItem.dataset_id == dataset.id, EvalItem.status == "verified")
    )
    if not verified:
        raise ValidationError(
            "This dataset has no verified questions yet.",
            hint="Add questions, or review the generated ones and accept those that are right.",
        )
    if kind == "rag":
        await ensure_llm_ready(settings)
    run = EvalRun(
        dataset_id=dataset.id,
        user_id=dataset.user_id,
        name=name.strip()[:200] or f"{config.get('mode', 'hybrid')} {kind}",
        kind=kind,
        config=config,
    )
    session.add(run)
    await session.flush()
    job = await jobs.enqueue(
        dataset.user_id, RUN_JOB, payload={"run_id": str(run.id)},
        subject_type="eval_run", subject_id=run.id,
    )  # fmt: skip
    run.job_id = job.id
    return run


async def request_generation(
    session: AsyncSession,
    settings: Settings,
    jobs: JobService,
    dataset: EvalDataset,
    count: int,
    document_ids: list[uuid.UUID],
) -> None:
    if dataset.generation.get("status") == "running":
        return
    await ensure_llm_ready(settings)
    dataset.generation = {"status": "running", "requested": count, "created": 0, "error": None}
    job = await jobs.enqueue(
        dataset.user_id,
        GENERATE_JOB,
        payload={
            "dataset_id": str(dataset.id),
            "count": count,
            "document_ids": [str(d) for d in document_ids],
        },
        subject_type="eval_dataset",
        subject_id=dataset.id,
    )
    dataset.generation = {**dataset.generation, "job_id": str(job.id)}


_PROSE_WORD = re.compile(r"[a-z][a-z'-]*[.,;:)]?")


def prose_ratio(text: str) -> float:
    """Share of plain lowercase words: low for figure labels, tables and reference lists."""
    words = text.split()
    return sum(1 for w in words if _PROSE_WORD.fullmatch(w)) / max(1, len(words))


async def sample_passages(
    session: AsyncSession, user_id: uuid.UUID, count: int, document_ids: list[uuid.UUID]
) -> list[tuple[Chunk, str]]:
    """Text passages of substance, spread over papers (round robin), deterministic."""
    query = (
        select(Chunk, Document.title)
        .join(Document, Document.current_version_id == Chunk.version_id)
        .where(
            Chunk.user_id == user_id,
            Document.status == DocumentStatus.READY,
            Chunk.kind == "text",
            Chunk.section_kind.not_in(SKIP_SECTIONS),
            Chunk.token_count >= 60,
        )
    )
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    rows = list((await session.execute(query.order_by(Chunk.document_id, Chunk.chunk_index))).all())
    by_paper: dict[uuid.UUID, list[tuple[Chunk, str]]] = {}
    for chunk, title in rows:
        if prose_ratio(chunk.text) < 0.5:  # measured: ~5% of passages, all figure/table text
            continue
        by_paper.setdefault(chunk.document_id, []).append((chunk, title))
    rng = random.Random(13)
    for chunks in by_paper.values():
        rng.shuffle(chunks)
    picked: list[tuple[Chunk, str]] = []
    while len(picked) < count and any(by_paper.values()):
        for paper in list(by_paper):
            if by_paper[paper] and len(picked) < count:
                picked.append(by_paper[paper].pop())
    return picked


_QUESTION = re.compile(r"[^\n?]{12,300}\?")


def parse_question(reply: str) -> str | None:
    match = _QUESTION.search(reply.strip().strip('"'))
    if not match:
        return None
    question = re.sub(r"^\s*(?:question\s*:|\d+[.)])\s*", "", match.group(0), flags=re.I).strip(
        ' "'
    )
    return question if len(question.split()) >= 4 else None


async def generate_questions(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    dataset_id: uuid.UUID,
    count: int,
    document_ids: list[uuid.UUID],
    report: Report,
) -> dict[str, Any]:
    started = time.perf_counter()
    async with session_factory() as session:
        dataset = await session.get(EvalDataset, dataset_id)
        if dataset is None:
            return {"status": "deleted"}
        user_id = dataset.user_id
        passages = await sample_passages(session, user_id, min(count, MAX_GENERATED), document_ids)
        for chunk, _ in passages:
            session.expunge(chunk)
    llm = get_llm(settings)
    params = GenerationParams(80, 0.3)
    created, skipped = 0, 0
    for index, (chunk, title) in enumerate(passages):
        await report(
            "generating", index / max(len(passages), 1), f"Question {index + 1} of {len(passages)}"
        )
        reply = await complete(
            llm,
            [
                Message("system", GENERATION_SYSTEM),
                Message("user", f"Paper: {title}\nPassage: {' '.join(chunk.text.split())}"),
            ],
            params,
        )
        question = parse_question(reply.text)
        if question is None:
            skipped += 1
            continue
        async with session_factory() as session:
            session.add(
                EvalItem(
                    dataset_id=dataset_id,
                    user_id=user_id,
                    question=question,
                    expected=[
                        {
                            "document_id": str(chunk.document_id),
                            "version_id": str(chunk.version_id),
                            "char_start": chunk.char_start,
                            "char_end": chunk.char_end,
                            "page": chunk.page_start,
                            "quote": chunk.text[:600],
                            "title": title,
                        }
                    ],
                    source="generated",
                    status="unverified",
                )
            )
            await session.commit()
        created += 1
    async with session_factory() as session:
        dataset = await session.get(EvalDataset, dataset_id)
        if dataset is not None:
            dataset.generation = {
                **dataset.generation,
                "status": "done",
                "created": created,
                "skipped": skipped,
                "seconds": round(time.perf_counter() - started, 1),
            }
            await session.commit()
    return {"created": created, "skipped": skipped}
