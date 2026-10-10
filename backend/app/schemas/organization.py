from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.organization import AnchorType, BookmarkKind, CollectionKind, ReadingStatus
from app.schemas.common import APIModel
from app.schemas.document import DocumentSummary, TagRef


class CollectionRef(BaseModel):
    id: uuid.UUID
    name: str


# --- collections ---------------------------------------------------------------------------------


class CollectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=4000)
    kind: CollectionKind = CollectionKind.PROJECT
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class CollectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    kind: CollectionKind | None = None


class CollectionOut(APIModel):
    id: uuid.UUID
    name: str
    description: str
    kind: CollectionKind
    paper_count: int = 0
    note_count: int = 0
    created_at: datetime
    updated_at: datetime


class CollectionDetail(CollectionOut):
    documents: list[DocumentSummary]


class CollectionPapers(BaseModel):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)


class AddedPapers(BaseModel):
    added: int
    paper_count: int


# --- tags ----------------------------------------------------------------------------------------


class TagOut(APIModel):
    id: uuid.UUID
    name: str
    color: str | None
    paper_count: int = 0


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    color: str | None = Field(default=None, max_length=16, pattern=r"^(#[0-9a-fA-F]{6}|[a-z]+)?$")


class DocumentTagsIn(BaseModel):
    names: list[str] = Field(max_length=20)


class ReadingStatusIn(BaseModel):
    status: ReadingStatus | None


class DocumentOrganization(BaseModel):
    tags: list[TagRef]
    reading_status: ReadingStatus | None
    bookmarked: bool
    collections: list[CollectionRef]


# --- notes ---------------------------------------------------------------------------------------


class Anchor(BaseModel):
    """Where a note points. Snapshot fields (page, quote, boxes) survive reprocessing."""

    type: AnchorType = AnchorType.PAPER
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    quote: str | None = Field(default=None, max_length=4000)
    boxes: list[list[float]] = Field(default_factory=list, max_length=200)
    section_title: str | None = Field(default=None, max_length=500)
    chunk_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None
    citation_number: int | None = None


class NoteCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    document_id: uuid.UUID | None = None
    collection_id: uuid.UUID | None = None
    anchor: Anchor | None = None


class NoteUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=20000)


class NoteOut(APIModel):
    id: uuid.UUID
    content: str
    document_id: uuid.UUID | None
    collection_id: uuid.UUID | None
    anchor: dict[str, Any] | None
    document_title: str | None = None
    created_at: datetime
    updated_at: datetime


# --- bookmarks -----------------------------------------------------------------------------------


class BookmarkTarget(BaseModel):
    page: int | None = None
    char_start: int | None = None
    quote: str | None = Field(default=None, max_length=4000)
    boxes: list[list[float]] = Field(default_factory=list, max_length=200)
    section_title: str | None = Field(default=None, max_length=500)
    element_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    message_id: uuid.UUID | None = None


class BookmarkCreate(BaseModel):
    document_id: uuid.UUID
    kind: BookmarkKind = BookmarkKind.PAPER
    target: BookmarkTarget = Field(default_factory=BookmarkTarget)
    label: str = Field(default="", max_length=300)


class BookmarkOut(APIModel):
    id: uuid.UUID
    document_id: uuid.UUID
    kind: BookmarkKind
    target: dict[str, Any]
    label: str
    document_title: str | None = None
    document_year: int | None = None
    created_at: datetime
