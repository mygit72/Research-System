from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.document import DocumentStatus
from app.schemas.common import APIModel


class Author(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    affiliation: str | None = Field(default=None, max_length=300)
    email: str | None = Field(default=None, max_length=320)


class ProcessingProgress(APIModel):
    job_id: uuid.UUID
    status: str
    stage: str
    stage_detail: str | None
    progress: float
    started_at: datetime | None
    error_message: str | None


class DocumentAssets(BaseModel):
    """Signed URLs (valid ~1h). `page_template` has `{page}` and `{width}` placeholders."""

    thumbnail: str | None
    file: str
    page_template: str | None


class TagRef(BaseModel):
    id: uuid.UUID
    name: str
    color: str | None = None


class DocumentSummary(APIModel):
    id: uuid.UUID
    title: str
    doc_type: str
    status: DocumentStatus
    authors_display: str
    year: int | None
    page_count: int | None
    original_filename: str
    error_message: str | None
    warnings: list[str]
    duplicate_kind: str | None
    duplicate_of_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_opened_at: datetime | None
    index_status: str
    index_error: str | None
    venue: str | None = None
    assets: DocumentAssets | None = None
    processing: ProcessingProgress | None = None
    reading_status: str | None = None  # to_read | reading | done
    tags: list[TagRef] = Field(default_factory=list)
    bookmarked: bool = False


class MetadataResponse(APIModel):
    title: str | None
    authors: list[Author]
    affiliations: list[str]
    abstract: str | None
    year: int | None
    publication_date: str | None
    venue: str | None
    doi: str | None
    arxiv_id: str | None
    keywords: list[str]
    research_area: str | None
    provenance: dict[str, Any]
    user_corrected_fields: list[str]


class VersionResponse(APIModel):
    id: uuid.UUID
    version_number: int
    original_filename: str
    file_size: int
    mime_type: str
    paginated: bool
    page_count: int | None
    used_ocr: bool
    ocr_pages: list[int]
    parser: str | None
    processing_config: dict[str, Any]
    processed_at: datetime | None
    embedding_model: str | None
    embedding_dimension: int | None
    chunking_strategy: str | None
    chunk_count: int
    indexed_at: datetime | None
    created_at: datetime


class DuplicateInfo(BaseModel):
    kind: str
    document_id: uuid.UUID
    title: str


class DocumentDetail(DocumentSummary):
    metadata: MetadataResponse | None
    version: VersionResponse | None
    version_count: int
    duplicate_of: DuplicateInfo | None = None


class UploadError(BaseModel):
    filename: str
    message: str
    hint: str | None = None


class UploadResponse(BaseModel):
    items: list[DocumentSummary]
    errors: list[UploadError]


class SkippedFile(BaseModel):
    filename: str
    reason: str


class ZipImportResponse(UploadResponse):
    skipped: list[SkippedFile]
    collection_id: uuid.UUID | None = None


class ImportRequest(BaseModel):
    refs: list[str] = Field(min_length=1, max_length=10, description="arXiv ids or links, or DOIs")


class DoiRequest(BaseModel):
    doi: str = Field(min_length=7, max_length=200, description="A DOI or doi.org link")


class MetadataUpdate(BaseModel):
    """User corrections. Only provided fields change; they're protected from reprocessing."""

    model_config = {"extra": "forbid"}

    title: str | None = Field(default=None, min_length=1, max_length=500)
    authors: list[Author] | None = Field(default=None, max_length=200)
    abstract: str | None = Field(default=None, max_length=20000)
    year: int | None = Field(default=None, ge=1500, le=2100)
    publication_date: str | None = Field(default=None, max_length=32)
    venue: str | None = Field(default=None, max_length=300)
    doi: str | None = Field(default=None, max_length=200)
    arxiv_id: str | None = Field(default=None, max_length=32)
    keywords: list[str] | None = Field(default=None, max_length=50)
    research_area: str | None = Field(default=None, max_length=120)

    @field_validator("doi")
    @classmethod
    def _clean_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().removeprefix("https://doi.org/").removeprefix("doi:")
        if value and not value.startswith("10."):
            raise ValueError("A DOI starts with “10.”, e.g. 10.1145/1571941.1572114")
        return value or None


class DuplicateResolution(BaseModel):
    action: Literal["keep_both", "merge_as_version", "delete"]


class ParagraphOut(BaseModel):
    text: str
    kind: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    boxes: list[list[float]]


class SectionOut(APIModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    level: int
    kind: str
    title: str
    number: str | None
    page_start: int
    page_end: int
    paragraphs: list[ParagraphOut]


class ElementOut(APIModel):
    id: uuid.UUID
    kind: str
    label: str | None
    number: str | None
    caption: str | None
    page: int
    bbox: list[float] | None
    content: dict[str, Any]
    context: str | None


class ReferenceOut(APIModel):
    position: int
    raw_text: str
    title: str | None
    year: int | None
    doi: str | None
    arxiv_id: str | None


class PageOut(APIModel):
    number: int
    width: float | None
    height: float | None
    used_ocr: bool


class DocumentStructureResponse(BaseModel):
    version_id: uuid.UUID
    paginated: bool
    pages: list[PageOut]
    sections: list[SectionOut]
    elements: list[ElementOut]
    references: list[ReferenceOut]


class ChunkOut(APIModel):
    id: uuid.UUID
    chunk_index: int
    strategy: str
    kind: str
    text: str
    context_header: str
    section_title: str
    section_kind: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    token_count: int
    boxes: list[list[float]]


class SimilarPaperOut(BaseModel):
    document: DocumentSummary
    score: float
    reasons: list[str]


class SimilarPapersResponse(BaseModel):
    status: Literal["ok", "not_indexed", "no_other_papers"]
    items: list[SimilarPaperOut]


class LibraryStats(BaseModel):
    total: int
    ready: int
    processing: int
    failed: int
    duplicates: int
