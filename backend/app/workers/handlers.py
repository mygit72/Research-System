"""Import every module that defines job handlers so they register at startup."""

from app.workers import (  # noqa: F401
    comparisons,
    documents,
    evaluation,
    projects,
    reports,
    summaries,
    topics,
)
