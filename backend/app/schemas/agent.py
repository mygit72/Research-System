from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import APIModel


class WatchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    query: str = Field(min_length=1, max_length=500)
    collection_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_import: bool = False
    synthesize: bool = False
    is_public: bool = False


class WatchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    collection_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    interval_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    relevance_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    auto_import: bool | None = None
    synthesize: bool | None = None
    is_public: bool | None = None
    status: Literal["active", "paused"] | None = None


class RunOut(APIModel):
    id: uuid.UUID
    watch_id: uuid.UUID
    status: str
    trigger: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    candidates_found: int
    candidates_above_threshold: int
    imported_count: int
    error_message: str | None
    report_id: uuid.UUID | None


class WatchOut(APIModel):
    id: uuid.UUID
    name: str
    query: str
    collection_id: uuid.UUID | None
    project_id: uuid.UUID | None
    interval_hours: int
    relevance_threshold: float
    auto_import: bool
    synthesize: bool
    is_public: bool
    status: str
    last_searched_at: datetime | None
    next_run_at: datetime
    created_at: datetime
    updated_at: datetime
    latest_run: RunOut | None = None


class DigestEntryOut(APIModel):
    id: uuid.UUID
    run_id: uuid.UUID
    watch_id: uuid.UUID
    arxiv_id: str
    title: str
    authors: list[dict[str, Any]]
    abstract: str
    published: str | None
    score: float
    blurb: str | None
    document_id: uuid.UUID | None
    import_status: str
    created_at: datetime
    trace: dict[str, Any]


# --- Public (no login): only what's already public on arXiv, for a watch marked is_public ----


class PublicWatchOut(APIModel):
    id: uuid.UUID
    name: str
    query: str
    status: str
    created_at: datetime


class PublicDigestEntryOut(APIModel):
    id: uuid.UUID
    arxiv_id: str
    title: str
    authors: list[dict[str, Any]]
    abstract: str
    published: str | None
    score: float
    blurb: str | None
    created_at: datetime
