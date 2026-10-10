"""Research projects: a guided plan from an idea to a paper outline (Phase 12).

A project walks through steps — research questions, background (a literature review),
gap and hypothesis, method plan, experiments and milestones, paper outline. Each step keeps
what the system suggested (with the evidence behind it) separately from what the user
chose or wrote, so it is always clear which is which.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class ResearchProject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "research_projects"
    __table_args__ = (Index("ix_research_projects_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    idea: Mapped[str] = mapped_column(Text, default="")
    # The papers the project builds on (optional; otherwise found from the idea / question).
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="SET NULL")
    )
    question: Mapped[str] = mapped_column(Text, default="")  # the chosen research question
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    # Per step: {status, suggestions…, chosen…, error, updated_at}; see services/projects.
    steps: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
