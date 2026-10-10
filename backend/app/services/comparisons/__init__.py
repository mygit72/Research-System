"""Comparing 2 to 5 papers: a cited, checked table per category plus an overview."""

from app.services.comparisons.generate import (
    ComparisonFailedError,
    ComparisonGone,
    agreement,
    generate_comparison,
)
from app.services.comparisons.service import (
    COMPARISON_JOB,
    get_comparison,
    list_comparisons,
    paper_states,
    progress,
    request_comparison,
)
from app.services.comparisons.spec import MAX_PAPERS, MIN_PAPERS, ROWS, ComparisonKind

__all__ = [
    "COMPARISON_JOB",
    "MAX_PAPERS",
    "MIN_PAPERS",
    "ROWS",
    "ComparisonFailedError",
    "ComparisonGone",
    "ComparisonKind",
    "agreement",
    "generate_comparison",
    "get_comparison",
    "list_comparisons",
    "paper_states",
    "progress",
    "request_comparison",
]
