"""Generated research reports: literature reviews, research gaps, disagreements, deep research.

One table for the four kinds: they share the lifecycle (queued → running → ready / failed,
one background job), the numbered `sources` every statement cites, the verification
summary and the editable `sections`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class ReportKind(StrEnum):
    REVIEW = "review"
    GAPS = "gaps"
    DISAGREEMENTS = "disagreements"
    DEEP_RESEARCH = "deep_research"


class ReportStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class ResearchReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_reports"
    __table_args__ = (Index("ix_research_reports_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(300))
    query: Mapped[str] = mapped_column(Text, default="")  # topic or research question
    # What was asked for: document_ids, collection_id, depth.
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="SET NULL")
    )
    # Papers actually used (ids; titles are kept in `sources` / sections for deleted papers).
    document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(16), default=ReportStatus.QUEUED)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # [{key, title, kind (text | chronology | table | gaps | disagreements | answer), text
    #   (Markdown with [n] citations), claims, status, label, data}] in display order.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    support: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    generation_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
