"""`agent.run_watch` job: run one Research Watch (see `services/agent/runner.py` for the work)."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.agent import AgentRun, RunStatus
from app.models.base import utcnow
from app.services.agent import WATCH_RUN_JOB
from app.services.agent.runner import execute_run
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted

GENERIC_FAILURE = "The watch couldn't run this time. It will try again on its next schedule."


async def _fail(ctx: JobContext, run_id: uuid.UUID, message: str) -> None:
    async with ctx.session_factory() as session:
        run = await session.get(AgentRun, run_id)
        if run is not None:
            run.status = RunStatus.FAILED
            run.error_message = message
            run.finished_at = utcnow()
            await session.commit()


@on_interrupted(WATCH_RUN_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _fail(ctx, uuid.UUID(ctx.payload["run_id"]), message)


@job_handler(WATCH_RUN_JOB)
async def run_watch(ctx: JobContext) -> dict[str, Any]:
    run_id = uuid.UUID(ctx.payload["run_id"])
    try:
        return await execute_run(ctx.session_factory, get_settings(), run_id, ctx.report)
    except AppError as exc:
        message = exc.message
    except Exception:
        message = GENERIC_FAILURE
    await _fail(ctx, run_id, message)
    raise JobFailedError(message)
