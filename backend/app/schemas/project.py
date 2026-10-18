from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

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


class CodeFileEdit(BaseModel):
    path: str = Field(min_length=1, max_length=120)
    content: str = Field(max_length=200_000)


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


class AttentionExperimentRequest(BaseModel):
    score_divisor: float = Field(default=1.0, ge=0.25, le=4.0)


class ClaimEvidenceRequest(BaseModel):
    claim: str = Field(min_length=12, max_length=600)


class ClaimStressTestRequest(BaseModel):
    claim: str = Field(min_length=12, max_length=600)
    evidence_chunk_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    dimensions: list[int] = Field(default_factory=lambda: [4, 16, 64, 256], min_length=2, max_length=5)
    seed: int = Field(default=42, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def validate_experiment(self) -> ClaimStressTestRequest:
        if len(set(self.evidence_chunk_ids)) != len(self.evidence_chunk_ids):
            raise ValueError("Choose each evidence passage only once.")
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("Key dimensions must be unique.")
        if any(dimension < 2 or dimension > 256 for dimension in self.dimensions):
            raise ValueError("Key dimensions must be between 2 and 256.")
        return self


class ResultsAnalysisRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    filename: str = Field(default="results.csv", min_length=1, max_length=255)


class PaperRunMatchRequest(BaseModel):
    result_analysis_id: uuid.UUID
    run_experiment: str = Field(min_length=1, max_length=200)
    run_dataset: str = Field(min_length=1, max_length=200)
    run_system: str = Field(min_length=1, max_length=200)
    run_metric: str = Field(min_length=1, max_length=120)
    run_split: str = Field(min_length=1, max_length=120)
    evidence_chunk_id: uuid.UUID
    paper_dataset: str = Field(min_length=1, max_length=200)
    paper_system: str = Field(min_length=1, max_length=200)
    paper_metric: str = Field(min_length=1, max_length=120)
    paper_split: str = Field(min_length=1, max_length=120)
    reported_mean: float = Field(allow_inf_nan=False)
    reported_std: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    tolerance: float = Field(default=0.02, ge=0, allow_inf_nan=False)
    map_labels: bool = False
    mapping_note: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_match(self) -> PaperRunMatchRequest:
        for name in (
            "run_experiment", "run_dataset", "run_system", "run_metric", "run_split",
            "paper_dataset", "paper_system", "paper_metric", "paper_split",
        ):
            value = getattr(self, name).strip()
            if not value:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} cannot be blank.")
            setattr(self, name, value)
        if self.mapping_note is not None:
            self.mapping_note = self.mapping_note.strip() or None
        if self.map_labels and (self.mapping_note is None or len(self.mapping_note) < 8):
            raise ValueError("Explain the label mapping in at least 8 characters.")
        return self


class PredictionAnalysisRequest(BaseModel):
    jsonl_text: str = Field(min_length=1, max_length=10_000_000)
    filename: str = Field(default="predictions.jsonl", min_length=1, max_length=255)
    metric: str = Field(min_length=1, max_length=120)
    higher_is_better: bool = True


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
