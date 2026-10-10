"""Collections, tags, notes, bookmarks and reading status — the user's own organization."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationError
from app.models.base import utcnow
from app.models.document import Document, DocumentMetadata
from app.models.organization import (
    Bookmark,
    BookmarkKind,
    Collection,
    CollectionDocument,
    DocumentTag,
    Note,
    Tag,
)
from app.services.citation_export import Reference

MAX_TAGS_PER_PAPER = 20


# --- ownership ---------------------------------------------------------------------------------


async def owned_documents(
    session: AsyncSession, user_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> list[Document]:
    ids = list(dict.fromkeys(document_ids))
    if not ids:
        return []
    rows = (
        await session.execute(
            select(Document).where(Document.id.in_(ids), Document.user_id == user_id)
        )
    ).scalars()
    found = {d.id: d for d in rows}
    if len(found) != len(ids):
        raise NotFoundError("Some of these papers don't exist.")
    return [found[i] for i in ids]


async def get_document(
    session: AsyncSession, user_id: uuid.UUID, document_id: uuid.UUID
) -> Document:
    return (await owned_documents(session, user_id, [document_id]))[0]


# --- collections ---------------------------------------------------------------------------------


async def get_collection(
    session: AsyncSession, user_id: uuid.UUID, collection_id: uuid.UUID
) -> Collection:
    collection = await session.get(Collection, collection_id)
    if collection is None or collection.user_id != user_id:
        raise NotFoundError("Collection not found.")
    return collection


async def collection_counts(
    session: AsyncSession, collection_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """collection id → (papers, notes)."""
    if not collection_ids:
        return {}
    papers = dict(
        (
            await session.execute(
                select(CollectionDocument.collection_id, func.count())
                .where(CollectionDocument.collection_id.in_(collection_ids))
                .group_by(CollectionDocument.collection_id)
            )
        ).all()
    )
    notes = dict(
        (
            await session.execute(
                select(Note.collection_id, func.count())
                .where(Note.collection_id.in_(collection_ids))
                .group_by(Note.collection_id)
            )
        ).all()
    )
    return {c: (int(papers.get(c, 0)), int(notes.get(c, 0))) for c in collection_ids}


async def list_collections(session: AsyncSession, user_id: uuid.UUID) -> list[Collection]:
    return list(
        (
            await session.execute(
                select(Collection)
                .where(Collection.user_id == user_id)
                .order_by(Collection.updated_at.desc())
            )
        ).scalars()
    )


async def collection_document_ids(
    session: AsyncSession, collection_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = await session.execute(
        select(CollectionDocument.document_id)
        .where(CollectionDocument.collection_id == collection_id)
        .order_by(CollectionDocument.added_at)
    )
    return list(rows.scalars())


async def add_to_collection(
    session: AsyncSession, user_id: uuid.UUID, collection: Collection, document_ids: list[uuid.UUID]
) -> int:
    """Add papers (already-present ones are skipped). Returns how many were added."""
    await owned_documents(session, user_id, document_ids)
    present = set(await collection_document_ids(session, collection.id))
    added = [d for d in dict.fromkeys(document_ids) if d not in present]
    for document_id in added:
        session.add(CollectionDocument(collection_id=collection.id, document_id=document_id))
    if added:
        collection.updated_at = utcnow()
    return len(added)


async def remove_from_collection(
    session: AsyncSession, collection: Collection, document_id: uuid.UUID
) -> None:
    await session.execute(
        delete(CollectionDocument).where(
            CollectionDocument.collection_id == collection.id,
            CollectionDocument.document_id == document_id,
        )
    )
    collection.updated_at = utcnow()


# --- tags ----------------------------------------------------------------------------------------


def clean_tag(name: str) -> str:
    name = re.sub(r"\s+", " ", name).strip().lstrip("#").strip()
    if not name:
        raise ValidationError("Tags can't be empty.")
    if len(name) > 60:
        raise ValidationError("Tags can be at most 60 characters.")
    return name


async def list_tags(session: AsyncSession, user_id: uuid.UUID) -> list[tuple[Tag, int]]:
    rows = await session.execute(
        select(Tag, func.count(DocumentTag.document_id))
        .outerjoin(DocumentTag, DocumentTag.tag_id == Tag.id)
        .where(Tag.user_id == user_id)
        .group_by(Tag.id)
        .order_by(func.lower(Tag.name))
    )
    return [(tag, int(count)) for tag, count in rows.all()]


async def get_tag(session: AsyncSession, user_id: uuid.UUID, tag_id: uuid.UUID) -> Tag:
    tag = await session.get(Tag, tag_id)
    if tag is None or tag.user_id != user_id:
        raise NotFoundError("Tag not found.")
    return tag


async def set_document_tags(
    session: AsyncSession, user_id: uuid.UUID, document: Document, names: list[str]
) -> list[Tag]:
    """Replace a paper's tags. Tags are created on first use; unused ones are removed."""
    first: dict[str, str] = {}
    for name in names:  # the first spelling wins: ["PEFT", "#peft"] → PEFT
        first.setdefault(clean_tag(name).casefold(), clean_tag(name))
    cleaned = list(first.items())
    if len(cleaned) > MAX_TAGS_PER_PAPER:
        raise ValidationError(f"A paper can have at most {MAX_TAGS_PER_PAPER} tags.")
    existing = {
        t.normalized: t
        for t in (
            await session.execute(
                select(Tag).where(
                    Tag.user_id == user_id, Tag.normalized.in_([key for key, _ in cleaned])
                )
            )
        ).scalars()
    }
    tags: list[Tag] = []
    for key, name in cleaned:
        tag = existing.get(key)
        if tag is None:
            tag = Tag(user_id=user_id, name=name, normalized=key)
            session.add(tag)
            await session.flush()
        tags.append(tag)
    previous = set(
        (
            await session.execute(
                select(DocumentTag.tag_id).where(DocumentTag.document_id == document.id)
            )
        ).scalars()
    )
    await session.execute(delete(DocumentTag).where(DocumentTag.document_id == document.id))
    for tag in tags:
        session.add(DocumentTag(document_id=document.id, tag_id=tag.id))
    await session.flush()
    await delete_unused_tags(session, previous - {t.id for t in tags})
    return tags


async def delete_unused_tags(session: AsyncSession, tag_ids: set[uuid.UUID]) -> None:
    if not tag_ids:
        return
    used = set(
        (
            await session.execute(
                select(DocumentTag.tag_id).where(DocumentTag.tag_id.in_(tag_ids)).distinct()
            )
        ).scalars()
    )
    if unused := tag_ids - used:
        await session.execute(delete(Tag).where(Tag.id.in_(unused)))


async def rename_tag(
    session: AsyncSession, user_id: uuid.UUID, tag: Tag, name: str | None, color: str | None
) -> Tag:
    if name is not None:
        cleaned = clean_tag(name)
        clash = await session.scalar(
            select(Tag).where(
                Tag.user_id == user_id, Tag.normalized == cleaned.casefold(), Tag.id != tag.id
            )
        )
        if clash is not None:
            raise ValidationError(f"You already have a tag called “{clash.name}”.")
        tag.name, tag.normalized = cleaned, cleaned.casefold()
    if color is not None:
        tag.color = color or None
    return tag


# --- per-paper organization info (batched for library listings) --------------------------------


async def organization_info(
    session: AsyncSession, user_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, Any]]:
    """document id → {tags: [{id, name, color}], bookmarked: bool}."""
    info: dict[uuid.UUID, dict[str, Any]] = {
        d: {"tags": [], "bookmarked": False} for d in document_ids
    }
    if not document_ids:
        return info
    rows = await session.execute(
        select(DocumentTag.document_id, Tag)
        .join(Tag, Tag.id == DocumentTag.tag_id)
        .where(DocumentTag.document_id.in_(document_ids))
        .order_by(func.lower(Tag.name))
    )
    for document_id, tag in rows.all():
        info[document_id]["tags"].append({"id": tag.id, "name": tag.name, "color": tag.color})
    bookmarked = await session.execute(
        select(Bookmark.document_id).where(
            Bookmark.user_id == user_id,
            Bookmark.kind == BookmarkKind.PAPER,
            Bookmark.document_id.in_(document_ids),
        )
    )
    for document_id in bookmarked.scalars():
        info[document_id]["bookmarked"] = True
    return info


async def document_collections(
    session: AsyncSession, document_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Collection.id, Collection.name)
        .join(CollectionDocument, CollectionDocument.collection_id == Collection.id)
        .where(CollectionDocument.document_id == document_id)
        .order_by(func.lower(Collection.name))
    )
    return [{"id": cid, "name": name} for cid, name in rows.all()]


async def documents_matching(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    collection_ids: list[uuid.UUID] | None = None,
    tags: list[str] | None = None,
) -> set[uuid.UUID] | None:
    """Papers in any of these collections AND with any of these tags (None: no restriction)."""
    result: set[uuid.UUID] | None = None
    if collection_ids:
        rows = await session.execute(
            select(CollectionDocument.document_id)
            .join(Collection, Collection.id == CollectionDocument.collection_id)
            .where(Collection.user_id == user_id, Collection.id.in_(collection_ids))
        )
        result = set(rows.scalars())
    if tags:
        wanted = [t.strip().lstrip("#").casefold() for t in tags if t.strip()]
        rows = await session.execute(
            select(DocumentTag.document_id)
            .join(Tag, Tag.id == DocumentTag.tag_id)
            .where(Tag.user_id == user_id, Tag.normalized.in_(wanted))
        )
        tagged = set(rows.scalars())
        result = tagged if result is None else result & tagged
    return result


# --- notes ---------------------------------------------------------------------------------------


async def get_note(session: AsyncSession, user_id: uuid.UUID, note_id: uuid.UUID) -> Note:
    note = await session.get(Note, note_id)
    if note is None or note.user_id != user_id:
        raise NotFoundError("Note not found.")
    return note


async def list_notes(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[Note]:
    query = select(Note).where(Note.user_id == user_id)
    if document_id is not None:
        query = query.where(Note.document_id == document_id)
    if collection_id is not None:
        query = query.where(Note.collection_id == collection_id)
    rows = await session.execute(query.order_by(Note.updated_at.desc()).limit(limit))
    return list(rows.scalars())


# --- bookmarks -----------------------------------------------------------------------------------


def bookmark_key(document_id: uuid.UUID, kind: str, target: dict[str, Any]) -> str:
    """One bookmark per thing: the paper, a passage (by char offset), an element, a citation."""
    point = {
        BookmarkKind.PAPER: "",
        BookmarkKind.PASSAGE: target.get("char_start"),
        BookmarkKind.TABLE: target.get("element_id") or target.get("char_start"),
        BookmarkKind.FIGURE: target.get("element_id") or target.get("char_start"),
        BookmarkKind.CITATION: target.get("chunk_id") or target.get("char_start"),
    }[BookmarkKind(kind)]
    return f"{document_id}:{kind}:{point if point is not None else target.get('page', '')}"


async def get_bookmark(
    session: AsyncSession, user_id: uuid.UUID, bookmark_id: uuid.UUID
) -> Bookmark:
    bookmark = await session.get(Bookmark, bookmark_id)
    if bookmark is None or bookmark.user_id != user_id:
        raise NotFoundError("Bookmark not found.")
    return bookmark


async def list_bookmarks(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    document_id: uuid.UUID | None = None,
    kinds: list[str] | None = None,
    limit: int = 200,
) -> list[Bookmark]:
    query = select(Bookmark).where(Bookmark.user_id == user_id)
    if document_id is not None:
        query = query.where(Bookmark.document_id == document_id)
    if kinds:
        query = query.where(Bookmark.kind.in_(kinds))
    rows = await session.execute(query.order_by(Bookmark.created_at.desc()).limit(limit))
    return list(rows.scalars())


async def document_titles(
    session: AsyncSession, document_ids: set[uuid.UUID]
) -> dict[uuid.UUID, tuple[str, int | None]]:
    if not document_ids:
        return {}
    rows = await session.execute(
        select(Document.id, Document.title, Document.year).where(Document.id.in_(document_ids))
    )
    return {i: (t, y) for i, t, y in rows.all()}


# --- citations ---------------------------------------------------------------------------------


async def references_for(
    session: AsyncSession, user_id: uuid.UUID, document_ids: list[uuid.UUID]
) -> list[Reference]:
    if not document_ids:
        return []
    documents = await owned_documents(session, user_id, document_ids)
    versions = [d.current_version_id for d in documents if d.current_version_id]
    metadata = {
        m.version_id: m
        for m in (
            await session.execute(
                select(DocumentMetadata).where(DocumentMetadata.version_id.in_(versions))
            )
        ).scalars()
    }
    references = []
    for document in documents:
        meta = metadata.get(document.current_version_id) if document.current_version_id else None
        authors = [a.get("name", "") for a in (meta.authors if meta else [])] or (
            [a.strip() for a in document.authors_display.split(",") if a.strip()]
        )
        references.append(
            Reference(
                title=document.title,
                authors=[a for a in authors if a],
                year=document.year,
                venue=meta.venue if meta else None,
                doi=meta.doi if meta else None,
                arxiv_id=meta.arxiv_id if meta else None,
                abstract=meta.abstract if meta else None,
                keywords=list(meta.keywords) if meta else [],
            )
        )
    return references
