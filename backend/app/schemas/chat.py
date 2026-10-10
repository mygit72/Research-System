from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.chat import ConversationScope
from app.schemas.common import APIModel


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    collection_id: uuid.UUID | None = Field(
        default=None, description="Chat about a collection: limited to its papers"
    )


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ConversationOut(APIModel):
    id: uuid.UUID
    title: str
    scope: ConversationScope
    document_ids: list[uuid.UUID]
    collection_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None


class CitationOut(APIModel):
    number: int
    chunk_id: uuid.UUID | None
    document_id: uuid.UUID | None
    document_title: str
    year: int | None
    section_title: str
    page_start: int
    page_end: int
    char_start: int
    quote: str
    boxes: list[list[float]]
    score: float
    cited: bool
    support_status: str | None


class MessageOut(APIModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    error: str | None
    support: dict[str, Any] | None
    retrieval_trace: dict[str, Any] | None
    generation_config: dict[str, Any] | None
    input_tokens: int
    output_tokens: int
    latency_ms: float | None
    created_at: datetime
    citations: list[CitationOut] = Field(default_factory=list)


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class AskIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # True: always write a new answer, even if an earlier near-identical one could be reused.
    fresh: bool = False
