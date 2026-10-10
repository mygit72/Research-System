"""Research chat: conversations, messages, and the citations each answer makes.

Every assistant message keeps what's needed to reproduce and audit it: the
retrieval trace (query analysis, search, context decisions), the generation
config (model, prompt version, retrieval settings) and token usage.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class ConversationScope(StrEnum):
    LIBRARY = "library"  # all of the user's papers
    PAPERS = "papers"  # a chosen set (paper chat = one paper)


class MessageStatus(StrEnum):
    COMPLETE = "complete"
    STOPPED = "stopped"  # the user stopped generation; partial answer kept
    ERROR = "error"


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    scope: Mapped[str] = mapped_column(String(16), default=ConversationScope.LIBRARY)
    document_ids: Mapped[list[str]] = mapped_column(JSONType, default=list)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A chat about a collection: scoped to the collection's papers when it was started.
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("collections.id", ondelete="SET NULL"), index=True
    )

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ChatMessage.created_at",
        lazy="raise",
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default=MessageStatus.COMPLETE)
    error: Mapped[str | None] = mapped_column(Text)
    support: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    retrieval_trace: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    generation_config: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    citations: Mapped[list[Citation]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Citation.number",
        lazy="raise",
    )


class Citation(UUIDPrimaryKeyMixin, Base):
    """One numbered source of an answer. Snapshot fields survive re-indexing or deletion."""

    __tablename__ = "citations"

    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("chunks.id", ondelete="SET NULL")
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    document_title: Mapped[str] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    section_title: Mapped[str] = mapped_column(String(500), default="")
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    quote: Mapped[str] = mapped_column(Text)
    boxes: Mapped[list[list[float]]] = mapped_column(JSONType, default=list)
    score: Mapped[float] = mapped_column(Float)
    cited: Mapped[bool] = mapped_column(default=False)  # used in the answer (vs. only provided)
    support_status: Mapped[str | None] = mapped_column(String(16))

    message: Mapped[ChatMessage] = relationship(back_populates="citations")
