"""Documents and everything extracted from them.

Document (user-facing paper, owns versions)
  └─ DocumentVersion (one uploaded file + its processing output)
       ├─ DocumentMetadata (1:1, user-correctable)
       ├─ Page*            (dimensions, char span in full_text, OCR flag)
       ├─ Section*         (hierarchy via parent_id; paragraphs with anchors)
       ├─ DocumentElement* (figures, tables, equations)
       └─ DocumentReference* (parsed bibliography)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin, utcnow


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class IndexStatus(StrEnum):
    """Search indexing is separate from reading: a paper can be readable but not yet searchable."""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class DuplicateKind(StrEnum):
    EXACT = "exact_duplicate"  # identical file bytes
    PROBABLE = "probable_duplicate"  # same DOI / arXiv ID / normalized title
    POSSIBLE = "possible_duplicate"  # very similar title


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_created", "user_id", "created_at"),
        Index("ix_documents_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    title_is_user_set: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[DocumentStatus] = mapped_column(String(16), default=DocumentStatus.QUEUED)
    doc_type: Mapped[str] = mapped_column(String(16))
    original_filename: Mapped[str] = mapped_column(String(255))
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True)
    )
    processing_job_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    error_message: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSONType, default=list)
    # Denormalized for fast library listing / sorting.
    year: Mapped[int | None] = mapped_column(Integer, index=True)
    authors_display: Mapped[str] = mapped_column(String(500), default="")
    page_count: Mapped[int | None] = mapped_column(Integer)
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    duplicate_kind: Mapped[str | None] = mapped_column(String(32))
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    index_status: Mapped[str] = mapped_column(String(16), default=IndexStatus.PENDING)
    index_error: Mapped[str | None] = mapped_column(Text)
    reading_status: Mapped[str | None] = mapped_column(String(16))  # to_read | reading | done

    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
        foreign_keys="DocumentVersion.document_id",
        order_by="DocumentVersion.version_number",
    )
    # lazy="raise": async code must load versions explicitly (no hidden I/O).
    current_version: Mapped[DocumentVersion | None] = relationship(
        foreign_keys=[current_version_id], post_update=True, lazy="raise", viewonly=True
    )


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number"),
        Index("ix_document_versions_user_hash", "user_id", "file_hash"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    storage_key: Mapped[str] = mapped_column(String(500))
    file_hash: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(120))
    original_filename: Mapped[str] = mapped_column(String(255))
    paginated: Mapped[bool] = mapped_column(Boolean, default=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    used_ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    ocr_pages: Mapped[list[int]] = mapped_column(JSONType, default=list)
    full_text: Mapped[str | None] = mapped_column(Text)
    parser: Mapped[str | None] = mapped_column(String(64))
    # Reproducibility: pipeline version, parser, options, stats and timings.
    processing_config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    has_thumbnail: Mapped[bool] = mapped_column(Boolean, default=False)
    # Search index record (reproducibility: which model/strategy produced the vectors).
    embedding_model: Mapped[str | None] = mapped_column(String(200))
    embedding_dimension: Mapped[int | None] = mapped_column(Integer)
    chunking_strategy: Mapped[str | None] = mapped_column(String(32))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="versions", foreign_keys=[document_id])
    metadata_record: Mapped[DocumentMetadata | None] = relationship(
        back_populates="version", cascade="all, delete-orphan", passive_deletes=True, uselist=False
    )


class DocumentMetadata(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_metadata"
    __table_args__ = (
        Index("ix_document_metadata_user_doi", "user_id", "doi"),
        Index("ix_document_metadata_user_arxiv", "user_id", "arxiv_id"),
        Index("ix_document_metadata_user_title", "user_id", "normalized_title"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(500))
    normalized_title: Mapped[str | None] = mapped_column(String(500))
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    affiliations: Mapped[list[str]] = mapped_column(JSONType, default=list)
    abstract: Mapped[str | None] = mapped_column(Text)
    year: Mapped[int | None] = mapped_column(Integer)
    publication_date: Mapped[str | None] = mapped_column(String(32))
    venue: Mapped[str | None] = mapped_column(String(300))
    doi: Mapped[str | None] = mapped_column(String(200))
    arxiv_id: Mapped[str | None] = mapped_column(String(32))
    keywords: Mapped[list[str]] = mapped_column(JSONType, default=list)
    research_area: Mapped[str | None] = mapped_column(String(120))
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Fields the user edited: reprocessing never overwrites them.
    user_corrected_fields: Mapped[list[str]] = mapped_column(JSONType, default=list)

    version: Mapped[DocumentVersion] = relationship(back_populates="metadata_record")


class Page(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "pages"
    __table_args__ = (UniqueConstraint("version_id", "number"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    width: Mapped[float | None] = mapped_column()
    height: Mapped[float | None] = mapped_column()
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    used_ocr: Mapped[bool] = mapped_column(Boolean, default=False)


class Section(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sections"
    __table_args__ = (Index("ix_sections_version_order", "version_id", "position"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sections.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)  # document order
    level: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(500))
    number: Mapped[str | None] = mapped_column(String(32))
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    # [{text, kind, page_start, page_end, char_start, char_end, boxes}]
    paragraphs: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)


class DocumentElement(UUIDPrimaryKeyMixin, Base):
    """A figure, table or equation."""

    __tablename__ = "document_elements"
    __table_args__ = (Index("ix_document_elements_version_kind", "version_id", "kind"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(16))
    position: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(64))
    number: Mapped[str | None] = mapped_column(String(16))
    caption: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int] = mapped_column(Integer)
    bbox: Mapped[list[float] | None] = mapped_column(JSONType)
    content: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    context: Mapped[str | None] = mapped_column(Text)


class DocumentReference(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_references"
    __table_args__ = (Index("ix_document_references_version", "version_id", "position"),)

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    year: Mapped[int | None] = mapped_column(Integer)
    doi: Mapped[str | None] = mapped_column(String(200))
    arxiv_id: Mapped[str | None] = mapped_column(String(32))


class Chunk(UUIDPrimaryKeyMixin, Base):
    """A retrievable passage with everything needed to cite it."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("version_id", "chunk_index"),
        Index("ix_chunks_user_document", "user_id", "document_id"),
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("document_versions.id", ondelete="CASCADE")
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    section_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("sections.id", ondelete="SET NULL")
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    strategy: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))  # text | table | equation | caption | code
    text: Mapped[str] = mapped_column(Text)
    context_header: Mapped[str] = mapped_column(String(1000), default="")
    section_title: Mapped[str] = mapped_column(String(500), default="")
    section_kind: Mapped[str] = mapped_column(String(32), default="other")
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    paragraph_index: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    boxes: Mapped[list[list[float]]] = mapped_column(JSONType, default=list)


class EmbeddingCache(Base):
    """Vectors keyed by (model, hash of the exact embedded text).

    Identical text is never embedded twice (re-uploads, reprocessing, versions),
    and the vector index can be rebuilt without recomputing embeddings.
    """

    __tablename__ = "embedding_cache"

    model_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    text_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    dimension: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now()
    )
