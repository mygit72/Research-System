from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.models.job import JobStatus
from app.schemas.common import APIModel


class JobResponse(APIModel):
    id: uuid.UUID
    kind: str
    status: JobStatus
    stage: str
    stage_detail: str | None
    progress: float
    subject_type: str | None
    subject_id: uuid.UUID | None
    result: dict[str, Any]
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
