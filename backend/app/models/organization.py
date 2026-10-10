"""Organizing a library: collections, tags, notes and bookmarks.

- A collection groups papers (and the notes and chats about them) for a project,
  review, thesis or course. Papers can be in several collections.
- Tags are the user's own labels on papers ("to cite", "baseline", "RAG").
- Notes are Markdown, attached to a paper (optionally anchored to a page, passage or
  chat citation) or to a collection.
- Bookmarks save a paper, passage, table, figure or citation to come back to.

Anchors and bookmark targets keep a snapshot (page, quote, boxes) so they still
point somewhere sensible after the paper is reprocessed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class CollectionKind(StrEnum):
    PROJECT = "project"
    REVIEW = "review"
    THESIS = "thesis"
    COURSE = "course"
    OTHER = "other"


class ReadingStatus(StrEnum):
    TO_READ = "to_read"
    READING = "reading"
    DONE = "done"


class BookmarkKind(StrEnum):
    PAPER = "paper"
    PASSAGE = "passage"
    TABLE = "table"
    FIGURE = "figure"
    CITATION = "citation"


class AnchorType(StrEnum):
    PAPER = "paper"
    PAGE = "page"
    PASSAGE = "passage"
    CITATION = "citation"


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "collections"
    __table_args__ = (Index("ix_collections_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default=CollectionKind.PROJECT)


class CollectionDocument(Base):
    __tablename__ = "collection_documents"

    collection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "normalized"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    normalized: Mapped[str] = mapped_column(String(60))  # casefolded: "RAG" == "rag"
    color: Mapped[str | None] = mapped_column(String(16))


class DocumentTag(Base):
    __tablename__ = "document_tags"

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Note(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (Index("ix_notes_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="CASCADE"), index=True
    )
    # {type: paper|page|passage|citation, page, char_start, char_end, quote, boxes,
    #  section_title, chunk_id, conversation_id, message_id, citation_number}
    anchor: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    content: Mapped[str] = mapped_column(Text)


class Bookmark(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (
        UniqueConstraint("user_id", "key"),
        Index("ix_bookmarks_user_created", "user_id", "created_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    # {page, char_start, quote, boxes, section_title, element_id, label, chunk_id, ...}
    target: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    label: Mapped[str] = mapped_column(String(300), default="")
    key: Mapped[str] = mapped_column(String(200))  # one bookmark per target
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
