from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import APIModel
from app.schemas.summary import SummaryClaimOut, SummaryProgress
from app.services.comparisons.spec import MAX_PAPERS, MIN_PAPERS, ComparisonKind


class ComparisonCreate(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=MIN_PAPERS, max_length=MAX_PAPERS)
    kind: ComparisonKind = ComparisonKind.PAPERS
    force: bool = Field(default=False, description="Write a new comparison even if one exists")


class ComparisonColumn(BaseModel):
    document_id: uuid.UUID
    version_id: uuid.UUID
    letter: str  # A, B, C… as the overview refers to the papers
    title: str
    year: int | None
    authors_display: str = ""
    extraction_id: uuid.UUID | None = None
    deleted: bool = False


class ComparisonCell(BaseModel):
    document_id: uuid.UUID
    letter: str
    text: str  # Markdown with [n] citations into `sources`, or "Not reported."
    citations: list[int]
    status: str  # supported | partial | unsupported | unverified | not_reported
    label: str
    explanation: str
    claims: list[SummaryClaimOut] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    key: str
    title: str
    # similar | different (words of the reported cells) | partial (some papers don't say) | none
    agreement: str
    cells: list[ComparisonCell]


class ComparisonOverview(BaseModel):
    text: str
    citations: list[int]
    status: str
    label: str
    explanation: str
    claims: list[SummaryClaimOut] = Field(default_factory=list)


class ComparisonSummary(APIModel):
    id: uuid.UUID
    title: str
    kind: ComparisonKind
    status: str
    columns: list[ComparisonColumn]
    created_at: datetime
    updated_at: datetime


class ComparisonOut(ComparisonSummary):
    rows: list[ComparisonRow]
    sources: list[dict[str, Any]]
    overview: ComparisonOverview | None
    support: dict[str, Any] | None
    generation_config: dict[str, Any]
    trace: dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_ms: float | None
    error_message: str | None
    error_hint: str | None = None
    progress: SummaryProgress | None = None
    stale: str | None = None
