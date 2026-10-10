"""`report.generate` job: literature reviews, gap and disagreement reports, deep research."""

from __future__ import annotations

import traceback
import uuid
from typing import Any

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.report import ReportStatus, ResearchReport
from app.services.analysis.reports import ReportGone, generate_report
from app.services.analysis.service import REPORT_JOB
from app.services.llm import LLMError
from app.services.summaries import SummaryFailedError
from app.workers.registry import JobContext, JobFailedError, job_handler, on_interrupted

GENERIC_FAILURE = "The report couldn't be written. Please try again."


async def _fail(ctx: JobContext, report_id: uuid.UUID, message: str, hint: str | None) -> None:
    async with ctx.session_factory() as session:
        report = await session.get(ResearchReport, report_id)
        if report is not None:
            report.status = ReportStatus.FAILED
            report.error_message = message
            report.trace = {**(report.trace or {}), "error_hint": hint}
            await session.commit()


@on_interrupted(REPORT_JOB)
async def interrupted(ctx: JobContext, message: str) -> None:
    await _fail(ctx, uuid.UUID(ctx.payload["report_id"]), message, None)


@job_handler(REPORT_JOB)
async def generate(ctx: JobContext) -> dict[str, Any]:
    report_id = uuid.UUID(ctx.payload["report_id"])
    try:
        return await generate_report(ctx.session_factory, get_settings(), report_id, ctx.report)
    except ReportGone:
        return {"status": "deleted"}
    except SummaryFailedError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except LLMError as exc:
        message, hint, detail = exc.user_message, exc.detail, exc.detail
    except AppError as exc:
        message, hint, detail = exc.message, exc.hint, exc.hint
    except Exception:
        message, hint, detail = GENERIC_FAILURE, None, traceback.format_exc()
    await _fail(ctx, report_id, message, hint)
    raise JobFailedError(message, detail=detail)
