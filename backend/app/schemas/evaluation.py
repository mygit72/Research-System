from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel
from app.schemas.summary import SummaryProgress


class DatasetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


class DatasetUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DatasetOut(APIModel):
    id: uuid.UUID
    name: str
    description: str
    generation: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    verified: int = 0
    unverified: int = 0
    runs: int = 0


class ItemCreate(BaseModel):
    question: str = Field(min_length=5, max_length=1000)
    chunk_ids: list[uuid.UUID] = Field(min_length=1, max_length=20, description="Expected passages")
    reference_answer: str = Field(default="", max_length=4000)


class ItemUpdate(BaseModel):
    question: str | None = Field(default=None, min_length=5, max_length=1000)
    chunk_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=20)
    reference_answer: str | None = Field(default=None, max_length=4000)
    status: Literal["verified", "unverified"] | None = None


class ItemOut(APIModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    question: str
    expected: list[dict[str, Any]]
    reference_answer: str
    source: str
    status: str
    created_at: datetime


class GenerateRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=30)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class RunConfig(BaseModel):
    mode: Literal["keyword", "semantic", "hybrid"] = Field(
        default="hybrid", description="keyword (BM25) | semantic (dense) | hybrid (RRF)"
    )
    rerank: bool = True
    top_k: int | None = Field(default=None, ge=5, le=200, description="Candidates per retriever")
    rerank_candidates: int | None = Field(default=None, ge=5, le=200)
    rrf_k: int | None = Field(default=None, ge=1, le=500)
    context_max_passages: int | None = Field(default=None, ge=1, le=20)


class RunCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    kind: Literal["retrieval", "rag"] = "retrieval"
    config: RunConfig = Field(default_factory=RunConfig)


class RunSummary(APIModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    name: str
    kind: str
    config: dict[str, Any]
    status: str
    metrics: dict[str, Any]
    items_evaluated: int
    latency_ms: float | None
    error_message: str | None
    created_at: datetime


class RunOut(RunSummary):
    per_item: list[dict[str, Any]]
    progress: SummaryProgress | None = None
