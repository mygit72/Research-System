"""`comparison.generate` job: read each paper (or reuse its cached fields), build the table."""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.comparison import Comparison, ComparisonStatus
from app.services.comparisons import (
    COMPARISON_JOB,
    ComparisonFailedError,
    ComparisonGone,
    generate_comparison,
)
from app.services.llm import LLMError
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted

GENERIC_FAILURE = "The comparison couldn't be written. Please try again."


async def _fail(ctx: JobContext, comparison_id: uuid.UUID, message: str, hint: str | None) -> None:
    async with ctx.session_factory() as session:
        comparison = await session.get(Comparison, comparison_id)
        if comparison is not None:
            comparison.status = ComparisonStatus.FAILED
            comparison.error_message = message
            comparison.trace = {**(comparison.trace or {}), "error_hint": hint}
            await session.commit()


@on_interrupted(COMPARISON_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _fail(ctx, uuid.UUID(ctx.payload["comparison_id"]), message, None)


@job_handler(COMPARISON_JOB)
async def compare_papers(ctx: JobContext) -> dict[str, Any]:
    comparison_id = uuid.UUID(ctx.payload["comparison_id"])
    try:
        return await generate_comparison(
            ctx.session_factory, get_settings(), comparison_id, ctx.report
        )
    except ComparisonGone:
        return {"status": "deleted"}
    except ComparisonFailedError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except LLMError as exc:
        message, hint, detail = exc.user_message, exc.detail, exc.detail
    except AppError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except Exception:
        message, hint, detail = GENERIC_FAILURE, None, traceback.format_exc()
    await _fail(ctx, comparison_id, message, hint)
    raise JobFailedError(message, detail=detail)
