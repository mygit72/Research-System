"""Research Watches: an autonomous agent that periodically searches arXiv for new papers on a
saved topic, scores them by embedding similarity, and records a digest (optionally importing the
best matches). See `services/agent/` for the behavior; this module only holds the tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class WatchStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunTrigger(StrEnum):
    SCHEDULED = "scheduled"
    MANUAL = "manual"


class ImportStatus(StrEnum):
    PENDING = "pending"
    IMPORTED = "imported"
    ALREADY_IN_LIBRARY = "already_in_library"


class AgentWatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "agent_watches"
    __table_args__ = (
        Index("ix_agent_watches_user_updated", "user_id", "updated_at"),
        Index("ix_agent_watches_status_next_run", "status", "next_run_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    query: Mapped[str] = mapped_column(Text)
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="SET NULL")
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_projects.id", ondelete="SET NULL")
    )
    interval_hours: Mapped[int] = mapped_column(Integer)
    relevance_threshold: Mapped[float] = mapped_column(Float)
    auto_import: Mapped[bool] = mapped_column(default=False)
    # Writes a full literature review (services/analysis) from the run's matches once there are
    # enough of them. Separate from auto_import: it imports the matches to read them even when
    # auto_import is off, so it is its own opt-in, not implied by anything else.
    synthesize: Mapped[bool] = mapped_column(default=False)
    # The watch's id doubles as its public token (already unguessable); this just gates whether
    # the public endpoints will serve it.
    is_public: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(16), default=WatchStatus.ACTIVE)
    last_searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set to now() at creation, so a brand-new watch is picked up by the very next tick.
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_watch_created", "watch_id", "created_at"),)

    watch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_watches.id", ondelete="CASCADE"), index=True
    )
    # Denormalized so the job payload and JobService.enqueue don't need a join.
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.QUEUED)
    trigger: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    searched_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    candidates_found: Mapped[int] = mapped_column(Integer, default=0)
    candidates_above_threshold: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Set when synthesize produced a literature review from this run's matches.
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("research_reports.id", ondelete="SET NULL")
    )


class AgentDigestEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "agent_digest_entries"
    __table_args__ = (Index("ix_agent_digest_entries_watch_created", "watch_id", "created_at"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_runs.id", ondelete="CASCADE"), index=True
    )
    # Denormalized: "every entry for this watch" without joining through agent_runs.
    watch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("agent_watches.id", ondelete="CASCADE")
    )
    arxiv_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500))
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    abstract: Mapped[str] = mapped_column(Text)
    published: Mapped[str | None] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    blurb: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    import_status: Mapped[str] = mapped_column(String(20), default=ImportStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Why this matched: search query, anchor text(s), rank among the run's candidates,
    # threshold — see services/agent/runner.py. Surfaced in the UI as "Why this matched".
    trace: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
