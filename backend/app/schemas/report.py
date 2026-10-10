from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel
from app.schemas.summary import SummaryProgress


class ReviewCreate(BaseModel):
    topic: str = Field(default="", max_length=300, description="What the review is about")
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    collection_id: uuid.UUID | None = None
    depth: Literal["brief", "standard", "detailed"] = Field(
        default="standard", description="Up to 6 / 10 / 16 papers"
    )


class PapersAnalysisCreate(BaseModel):
    """Research gaps or disagreements in chosen papers, a collection, or papers on a topic."""

    topic: str = Field(default="", max_length=300)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    collection_id: uuid.UUID | None = None
    depth: Literal["brief", "standard", "detailed"] = "standard"


class DeepResearchCreate(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=30)
    collection_id: uuid.UUID | None = None
    max_steps: int = Field(default=16, ge=3, le=40, description="Model calls + searches")
    token_budget: int = Field(default=30_000, ge=2_000, le=200_000)
    timeout_seconds: int = Field(default=900, ge=30, le=3_600)


class ReportSectionEdit(BaseModel):
    key: str
    title: str | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=20_000)


class ReportUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    sections: list[ReportSectionEdit] | None = None


class ReportSummary(APIModel):
    id: uuid.UUID
    kind: str
    title: str
    query: str
    status: str
    document_ids: list[str]
    collection_id: uuid.UUID | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    edited_at: datetime | None


class ReportOut(ReportSummary):
    params: dict[str, Any]
    sections: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    support: dict[str, Any] | None
    trace: dict[str, Any]
    generation_config: dict[str, Any]
    input_tokens: int
    output_tokens: int
    latency_ms: float | None
    progress: SummaryProgress | None = None
    error_hint: str | None = None
