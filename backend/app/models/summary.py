"""Structured paper summaries (problem → takeaway), each statement cited and checked.

One row per generation. The newest row for a document is the one shown; older
rows are removed once a newer one succeeds, so a regeneration never leaves the
paper without a summary while it runs. Everything needed to reproduce a summary
is kept: the version it was made from, the model, the prompt version and the
passages (snapshots, so citations survive re-indexing).
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class SummaryStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class PaperSummary(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_summaries"
    __table_args__ = (Index("ix_paper_summaries_document_created", "document_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16), default=SummaryStatus.QUEUED)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    # Cache key: same version + same model + same prompt version = same summary.
    config_key: Mapped[str] = mapped_column(String(300))
    # [{key, title, text, citations, status, claims: [...]}] in display order; filled
    # group by group while the summary is generated, so the UI can show it progressively.
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # Numbered passages the sections cite (same shape as chat evidence items).
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    support: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    generation_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
