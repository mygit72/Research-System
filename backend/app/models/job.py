from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A background unit of work (parsing, embedding, summarization, evaluation, ...).

    `stage` and `progress` drive the UI progress indicator; `error_message` is the
    user-safe explanation while `error_detail` keeps the technical cause for admins.
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_user_status", "user_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[JobStatus] = mapped_column(String(16), default=JobStatus.QUEUED)
    stage: Mapped[str] = mapped_column(String(64), default="queued")
    stage_detail: Mapped[str | None] = mapped_column(String(300))  # "Extracting page 12 of 38"
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    # Generic subject reference, e.g. ("document", <uuid>).
    subject_type: Mapped[str | None] = mapped_column(String(32))
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
