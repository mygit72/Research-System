"""`project.suggest` job: research-question suggestions and the paper outline."""

from __future__ import annotations

import copy
import uuid
from typing import Any

from app.core.config import get_settings
from app.models.project import ResearchProject
from app.services.projects.generate import run_step
from app.services.projects.service import PROJECT_JOB
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted


@on_interrupted(PROJECT_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    async with ctx.session_factory() as session:
        project = await session.get(ResearchProject, uuid.UUID(ctx.payload["project_id"]))
        if project is not None:
            steps = copy.deepcopy(project.steps)  # JSON isn't mutation-tracked
            step = ctx.payload["step"]
            steps[step] = {**steps.get(step, {}), "status": "failed", "error": message}
            project.steps = steps
            await session.commit()


@job_handler(PROJECT_JOB)
async def suggest(ctx: JobContext) -> dict[str, Any]:
    result = await run_step(
        ctx.session_factory,
        get_settings(),
        uuid.UUID(ctx.payload["project_id"]),
        ctx.payload["step"],
        ctx.report,
    )
    if result.get("error"):
        raise JobFailedError(str(result["error"]))
    return result
