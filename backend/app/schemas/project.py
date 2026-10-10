from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import APIModel
from app.schemas.report import ReportSummary
from app.schemas.summary import SummaryProgress


class ProjectCreate(BaseModel):
    idea: str = Field(min_length=3, max_length=4000)
    title: str | None = Field(default=None, max_length=300)
    collection_id: uuid.UUID | None = None


class MethodChoice(BaseModel):
    datasets: list[str] = Field(default_factory=list, max_length=20)
    baselines: list[str] = Field(default_factory=list, max_length=20)
    methods: list[str] = Field(default_factory=list, max_length=20)
    metrics: list[str] = Field(default_factory=list, max_length=20)


class OutlineEdit(BaseModel):
    key: str
    text: str = Field(max_length=20_000)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    idea: str | None = Field(default=None, max_length=4000)
    question: str | None = Field(default=None, max_length=1000)
    hypothesis: str | None = Field(default=None, max_length=2000)
    collection_id: uuid.UUID | None = None
    gap: dict[str, Any] | None = Field(default=None, description="The chosen gap ({} clears it)")
    methods: MethodChoice | None = None
    experiments: list[dict[str, Any]] | None = Field(default=None, max_length=30)
    milestones: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    outline: list[OutlineEdit] | None = None


class ExperimentPlanRequest(BaseModel):
    deadline: date | None = None
    replace: bool = Field(default=False, description="Replace experiments already planned")


class ProjectSummary(APIModel):
    id: uuid.UUID
    title: str
    idea: str
    question: str
    collection_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class NextStep(BaseModel):
    step: str | None = Field(description="The step to work on next; null when all are done")
    message: str


class ProjectGuidance(BaseModel):
    next_step: NextStep
    notes: list[str] = Field(default_factory=list, description="What would improve the suggestions")


class ProjectOut(ProjectSummary):
    hypothesis: str
    steps: dict[str, Any]
    completion: dict[str, bool] = Field(default_factory=dict)
    guidance: ProjectGuidance | None = None
    reports: dict[str, ReportSummary | None] = Field(default_factory=dict)
    progress: SummaryProgress | None = None
