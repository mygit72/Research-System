"""`paper.summarize` job: write, cite and check a paper's structured summary."""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.summary import PaperSummary, SummaryStatus
from app.services.llm import LLMError
from app.services.summaries import (
    SUMMARY_JOB,
    SummaryFailedError,
    SummaryGone,
    generate_summary,
)
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted

GENERIC_FAILURE = "The summary couldn't be written. Please try again."


async def _fail(ctx: JobContext, summary_id: uuid.UUID, message: str, hint: str | None) -> None:
    async with ctx.session_factory() as session:
        summary = await session.get(PaperSummary, summary_id)
        if summary is not None:
            summary.status = SummaryStatus.FAILED
            summary.error_message = message
            summary.trace = {**(summary.trace or {}), "error_hint": hint}
            await session.commit()


@on_interrupted(SUMMARY_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _fail(ctx, uuid.UUID(ctx.payload["summary_id"]), message, None)


@job_handler(SUMMARY_JOB)
async def summarize_paper(ctx: JobContext) -> dict[str, Any]:
    summary_id = uuid.UUID(ctx.payload["summary_id"])
    try:
        return await generate_summary(ctx.session_factory, get_settings(), summary_id, ctx.report)
    except SummaryGone:
        return {"status": "deleted"}
    except SummaryFailedError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except LLMError as exc:
        message, hint, detail = exc.user_message, exc.detail, exc.detail
    except AppError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except Exception:
        message, hint, detail = GENERIC_FAILURE, None, traceback.format_exc()
    await _fail(ctx, summary_id, message, hint)
    raise JobFailedError(message, detail=detail)
