"""Structured paper summaries: map over section groups, reduce to a takeaway, verify."""

from app.services.summaries.generate import SummaryFailedError, SummaryGone, generate_summary
from app.services.summaries.service import (
    SUMMARY_JOB,
    auto_summarize,
    config_key,
    job_progress,
    last_ready_summary,
    latest_summary,
    request_summary,
    staleness,
)
from app.services.summaries.spec import FIELDS, GROUPS, NOT_REPORTED, PROMPT_VERSION

__all__ = [
    "FIELDS",
    "GROUPS",
    "NOT_REPORTED",
    "PROMPT_VERSION",
    "SUMMARY_JOB",
    "SummaryFailedError",
    "SummaryGone",
    "auto_summarize",
    "config_key",
    "generate_summary",
    "job_progress",
    "last_ready_summary",
    "latest_summary",
    "request_summary",
    "staleness",
]
