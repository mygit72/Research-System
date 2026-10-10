"""Knowledge layer: entities found in papers, and topic clusterings of the library.

Entity (a dataset / model / method / metric / task, per user)
  └─ DocumentEntity* (paper ↔ entity with relation, mention count and evidence sentences)
EntityExtraction (per document version: what discovery found + which dictionary matched it)
TopicClustering (one clustering run of the user's papers: method, clusters, names, 2-D map)

Authors, institutions and in-library citations are derived from document metadata and
parsed references when needed (they always reflect the user's metadata corrections).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "key"),
        Index("ix_entities_user_type", "user_id", "type"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(16))  # dataset | model | method | metric | task
    key: Mapped[str] = mapped_column(String(200))  # normalized name (entity_key)
    name: Mapped[str] = mapped_column(String(300))
    aliases: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Reference facts from the built-in catalog (task, domain, size, license).
    info: Mapped[dict[str, str]] = mapped_column(JSONType, default=dict)
    source: Mapped[str] = mapped_column(String(16), default="catalog")  # catalog | discovered


class DocumentEntity(UUIDPrimaryKeyMixin, Base):
    """A paper's link to an entity: proposes / uses / mentions, with evidence."""

    __tablename__ = "document_entities"
    __table_args__ = (
        UniqueConstraint("version_id", "entity_id"),
        Index("ix_document_entities_user_entity", "user_id", "entity_id"),
        Index("ix_document_entities_document", "document_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("entities.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    relation: Mapped[str] = mapped_column(String(16))  # proposes | uses | mentions
    mentions: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    variants: Mapped[list[str]] = mapped_column(JSONType, default=list)  # "BERT-large", …
    # [{quote, page, section_kind, section_id, paragraph_index, surface}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)


class EntityExtraction(Base):
    """Per version: discovery output (independent of other papers) + the dictionary
    fingerprint its mentions were last matched with."""

    __tablename__ = "entity_extractions"

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    extractor_version: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(500), default="")  # discovery input
    discovered: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    dictionary_hash: Mapped[str | None] = mapped_column(String(32))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TopicClustering(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "topic_clusterings"
    __table_args__ = (Index("ix_topic_clusterings_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(24))  # kmeans | agglomerative | hdbscan
    params: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Which papers (current versions) and vectors this run used; differs → out of date.
    fingerprint: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(200))
    # {clusters: [{id, name, name_source, terms, document_ids, ...}], points: [...],
    #  quality: {...}, excluded: [...]}
    result: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    naming_status: Mapped[str] = mapped_column(String(16), default="pending")
    naming_model: Mapped[str | None] = mapped_column(String(200))
    job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_message: Mapped[str | None] = mapped_column(Text)
