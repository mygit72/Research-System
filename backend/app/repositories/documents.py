from __future__ import annotations

import uuid
from typing import Literal

from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import (
    Document,
    DocumentElement,
    DocumentMetadata,
    DocumentReference,
    DocumentStatus,
    DocumentVersion,
    Page,
    Section,
)
from app.models.organization import Bookmark

SortKey = Literal["recent", "opened", "published", "title"]


class DocumentRepository:
    def __init__(self, session: AsyncSession, demo_user_id: uuid.UUID | None = None) -> None:
        self.session = session
        if demo_user_id is None:
            from app.core.config import get_settings

            settings = get_settings()
            if settings.demo_mode:
                demo_user_id = settings.demo_user_id
        self.demo_user_id = demo_user_id

    async def get_for_user(self, document_id: uuid.UUID, user_id: uuid.UUID) -> Document | None:
        user_cond = (
            or_(Document.user_id == user_id, Document.user_id == self.demo_user_id)
            if self.demo_user_id
            else (Document.user_id == user_id)
        )
        result = await self.session.execute(
            select(Document).where(Document.id == document_id, user_cond)
        )
        return result.unique().scalar_one_or_none()

    async def get_version(self, version_id: uuid.UUID) -> DocumentVersion | None:
        return await self.session.get(DocumentVersion, version_id)

    async def list_versions(self, document_id: uuid.UUID) -> list[DocumentVersion]:
        result = await self.session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number)
        )
        return list(result.scalars())

    def _filtered(
        self, user_id: uuid.UUID, query: str | None, statuses: list[DocumentStatus] | None
    ) -> Select[tuple[Document]]:
        user_cond = (
            or_(Document.user_id == user_id, Document.user_id == self.demo_user_id)
            if self.demo_user_id
            else (Document.user_id == user_id)
        )
        stmt = select(Document).where(user_cond)
        if statuses:
            stmt = stmt.where(Document.status.in_(statuses))
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(
                    Document.title.ilike(pattern),
                    Document.authors_display.ilike(pattern),
                    Document.original_filename.ilike(pattern),
                )
            )
        return stmt

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        *,
        query: str | None = None,
        statuses: list[DocumentStatus] | None = None,
        sort: SortKey = "recent",
        limit: int = 50,
        offset: int = 0,
        only: set[uuid.UUID] | None = None,
        reading_status: str | None = None,
        bookmarked: bool | None = None,
    ) -> tuple[list[Document], int]:
        stmt = self._filtered(user_id, query, statuses)
        if only is not None:  # collection / tag filters, resolved by the caller
            stmt = stmt.where(Document.id.in_(only))
        if reading_status == "none":
            stmt = stmt.where(Document.reading_status.is_(None))
        elif reading_status:
            stmt = stmt.where(Document.reading_status == reading_status)
        if bookmarked is not None:
            paper_bookmarks = select(Bookmark.document_id).where(
                Bookmark.user_id == user_id, Bookmark.kind == "paper"
            )
            in_bookmarks = Document.id.in_(paper_bookmarks)
            stmt = stmt.where(in_bookmarks if bookmarked else ~in_bookmarks)
        total = await self.session.scalar(select(func.count()).select_from(stmt.subquery()))
        order = {
            "recent": [Document.created_at.desc()],
            "opened": [Document.last_opened_at.desc().nulls_last(), Document.created_at.desc()],
            "published": [Document.year.desc().nulls_last(), Document.created_at.desc()],
            "title": [func.lower(Document.title).asc()],
        }[sort]
        result = await self.session.execute(stmt.order_by(*order).limit(limit).offset(offset))
        return list(result.unique().scalars()), int(total or 0)

    async def status_counts(self, user_id: uuid.UUID) -> dict[str, int]:
        result = await self.session.execute(
            select(Document.status, func.count())
            .where(Document.user_id == user_id)
            .group_by(Document.status)
        )
        return {str(status): int(count) for status, count in result.all()}

    async def pending_duplicates(self, user_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).where(
                    Document.user_id == user_id, Document.duplicate_kind.is_not(None)
                )
            )
            or 0
        )

    async def find_version_by_hash(
        self, user_id: uuid.UUID, file_hash: str, exclude_document: uuid.UUID
    ) -> DocumentVersion | None:
        result = await self.session.execute(
            select(DocumentVersion)
            .where(
                DocumentVersion.user_id == user_id,
                DocumentVersion.file_hash == file_hash,
                DocumentVersion.document_id != exclude_document,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def metadata_candidates(
        self, user_id: uuid.UUID, exclude_document: uuid.UUID
    ) -> list[tuple[uuid.UUID, DocumentMetadata]]:
        """(document id, metadata of its current version) for every other document."""
        result = await self.session.execute(
            select(Document.id, DocumentMetadata)
            .join(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .join(DocumentMetadata, DocumentMetadata.version_id == DocumentVersion.id)
            .where(Document.user_id == user_id, Document.id != exclude_document)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_metadata(self, version_id: uuid.UUID) -> DocumentMetadata | None:
        result = await self.session.execute(
            select(DocumentMetadata).where(DocumentMetadata.version_id == version_id)
        )
        return result.scalar_one_or_none()

    async def sections(self, version_id: uuid.UUID) -> list[Section]:
        result = await self.session.execute(
            select(Section).where(Section.version_id == version_id).order_by(Section.position)
        )
        return list(result.scalars())

    async def pages(self, version_id: uuid.UUID) -> list[Page]:
        result = await self.session.execute(
            select(Page).where(Page.version_id == version_id).order_by(Page.number)
        )
        return list(result.scalars())

    async def elements(self, version_id: uuid.UUID) -> list[DocumentElement]:
        result = await self.session.execute(
            select(DocumentElement)
            .where(DocumentElement.version_id == version_id)
            .order_by(DocumentElement.position)
        )
        return list(result.scalars())

    async def references(self, version_id: uuid.UUID) -> list[DocumentReference]:
        result = await self.session.execute(
            select(DocumentReference)
            .where(DocumentReference.version_id == version_id)
            .order_by(DocumentReference.position)
        )
        return list(result.scalars())

    async def clear_extraction(self, version_id: uuid.UUID) -> None:
        """Remove previous processing output (reprocessing is idempotent)."""
        for model in (Page, DocumentElement, DocumentReference):
            await self.session.execute(delete(model).where(model.version_id == version_id))
        # Children first: sections reference their parent.
        await self.session.execute(
            delete(Section).where(Section.version_id == version_id, Section.parent_id.is_not(None))
        )
        await self.session.execute(delete(Section).where(Section.version_id == version_id))
