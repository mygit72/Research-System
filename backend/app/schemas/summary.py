from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import APIModel


class SummaryClaimOut(BaseModel):
    text: str
    citations: list[int]
    status: str  # supported | partial | unsupported | uncited
    entailment: float
    best_passage: int | None
    found_in: int | None = None


class SummarySectionOut(BaseModel):
    key: str  # problem | motivation | method | … | takeaway
    title: str
    text: str  # Markdown with [n] citations, or "Not reported."
    citations: list[int]
    invalid_citations: list[int] = Field(default_factory=list)
    status: str  # supported | partial | unsupported | unverified | not_reported
    label: str
    explanation: str
    claims: list[SummaryClaimOut] = Field(default_factory=list)


class SummaryProgress(BaseModel):
    stage: str
    detail: str | None
    progress: float


class SummaryOut(APIModel):
    id: uuid.UUID
    document_id: uuid.UUID
    version_id: uuid.UUID
    status: str  # queued | running | ready | failed
    sections: list[SummarySectionOut]
    # Numbered passages the sections cite (same shape as chat evidence items).
    sources: list[dict[str, Any]]
    support: dict[str, Any] | None
    generation_config: dict[str, Any]
    trace: dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_ms: float | None
    error_message: str | None
    error_hint: str | None = None
    progress: SummaryProgress | None = None
    stale: str | None = None  # why it no longer matches the paper / configuration
    # The last ready summary, while this one is being written or after it failed.
    previous: SummaryOut | None = None
    created_at: datetime
    updated_at: datetime


class SummaryRequest(BaseModel):
    force: bool = Field(default=False, description="Regenerate even if a cached summary exists")
