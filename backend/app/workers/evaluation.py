"""`eval.run` (measure a configuration) and `eval.generate` (write candidate questions)."""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.evaluation import EvalDataset, EvalRun
from app.services.evaluation.runner import RunGone, run_evaluation
from app.services.evaluation.service import GENERATE_JOB, RUN_JOB, generate_questions
from app.services.llm import LLMError
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted


def _message(exc: Exception) -> tuple[str, str | None]:
    if isinstance(exc, LLMError):
        return exc.user_message, exc.detail
    if isinstance(exc, AppError):
        return exc.message, exc.hint
    return "The evaluation couldn't be completed.", traceback.format_exc()


@on_interrupted(RUN_JOB, GENERATE_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    async with ctx.session_factory() as session:
        if ctx.kind == RUN_JOB:
            run = await session.get(EvalRun, uuid.UUID(ctx.payload["run_id"]))
            if run is not None:
                run.status, run.error_message = "failed", message
        else:
            dataset = await session.get(EvalDataset, uuid.UUID(ctx.payload["dataset_id"]))
            if dataset is not None:
                dataset.generation = {**dataset.generation, "status": "failed", "error": message}
        await session.commit()


@job_handler(RUN_JOB)
async def run(ctx: JobContext) -> dict[str, Any]:
    run_id = uuid.UUID(ctx.payload["run_id"])
    try:
        return await run_evaluation(ctx.session_factory, get_settings(), run_id, ctx.report)
    except RunGone:
        return {"status": "deleted"}
    except Exception as exc:
        message, detail = _message(exc)
        async with ctx.session_factory() as session:
            row = await session.get(EvalRun, run_id)
            if row is not None:
                row.status, row.error_message = "failed", message
                await session.commit()
        raise JobFailedError(message, detail=detail) from exc


@job_handler(GENERATE_JOB)
async def generate(ctx: JobContext) -> dict[str, Any]:
    dataset_id = uuid.UUID(ctx.payload["dataset_id"])
    try:
        return await generate_questions(
            ctx.session_factory,
            get_settings(),
            dataset_id,
            int(ctx.payload["count"]),
            [uuid.UUID(d) for d in ctx.payload.get("document_ids", [])],
            ctx.report,
        )
    except Exception as exc:
        message, detail = _message(exc)
        async with ctx.session_factory() as session:
            row = await session.get(EvalDataset, dataset_id)
            if row is not None:
                row.generation = {**row.generation, "status": "failed", "error": message}
                await session.commit()
        raise JobFailedError(message, detail=detail) from exc
