"""Evaluation: datasets of questions with expected evidence, and runs that measure against them.

EvalDataset ─┬─ EvalItem* (question, expected evidence spans, optional reference answer)
             └─ EvalRun*  (one configuration: retrieval or full RAG; aggregate + per-question
                           metrics, the configuration and the index it ran against)

Expected evidence is stored as character spans of a paper version (plus the quote), not as
chunk ids: a retrieved passage is relevant when it overlaps an expected span, so the same
dataset can compare chunking strategies and embedding models after re-indexing.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class EvalDataset(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_datasets"
    __table_args__ = (Index("ix_eval_datasets_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    # Status of the latest question-generation job, if any.
    generation: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class EvalItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_items"
    __table_args__ = (Index("ix_eval_items_dataset", "dataset_id", "created_at"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("eval_datasets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(Text)
    # [{document_id, version_id, char_start, char_end, page, quote, title}]
    expected: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    reference_answer: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | generated
    # Generated questions count only after a person checks them.
    status: Mapped[str] = mapped_column(String(16), default="verified")  # verified | unverified


class EvalRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "eval_runs"
    __table_args__ = (Index("ix_eval_runs_dataset_created", "dataset_id", "created_at"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("eval_datasets.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # retrieval | rag
    # Retrieval mode, reranker, k values… plus what the index was built with.
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # aggregates
    per_item: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    items_evaluated: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
