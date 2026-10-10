"""Paper comparisons and the per-paper extractions they are built from.

A comparison (2 to 5 papers) is a table: one row per category, one cited and checked
cell per paper, plus an overview written from the table. Cells come from a
`PaperExtraction` — the fields of one paper version for one kind of comparison,
cached by (version, kind, model, prompt version), so comparing a paper again with
other papers doesn't re-read it.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class ComparisonStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class Comparison(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "comparisons"
    __table_args__ = (Index("ix_comparisons_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(16))  # papers | methodology
    document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)  # column order
    status: Mapped[str] = mapped_column(String(16), default=ComparisonStatus.QUEUED)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    config_key: Mapped[str] = mapped_column(String(500), default="")
    # [{document_id, version_id, title, year, authors_display, extraction_id}]
    columns: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    # [{key, title, agreement, cells: [{document_id, text, citations, status, label, ...}]}]
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    overview: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    support: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    generation_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)


class PaperExtraction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paper_extractions"
    __table_args__ = (Index("ix_paper_extractions_version_key", "version_id", "config_key"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    config_key: Mapped[str] = mapped_column(String(500))
    sections: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    claims: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    trace: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    llm_model: Mapped[str | None] = mapped_column(String(200))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
