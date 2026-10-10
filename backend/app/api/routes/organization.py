"""Collections, tags, notes, bookmarks and reading status."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep
from app.core.errors import ValidationError
from app.models.document import Document
from app.models.organization import Bookmark, Collection, Note
from app.schemas.organization import (
    AddedPapers,
    BookmarkCreate,
    BookmarkOut,
    CollectionCreate,
    CollectionDetail,
    CollectionOut,
    CollectionPapers,
    CollectionUpdate,
    DocumentOrganization,
    DocumentTagsIn,
    NoteCreate,
    NoteOut,
    NoteUpdate,
    ReadingStatusIn,
    TagOut,
    TagUpdate,
)
from app.services import organization as org
from app.services.citation_export import bibtex, ris

router = APIRouter(tags=["organization"])


# --- collections ---------------------------------------------------------------------------------


async def _collection_out(db: DbSession, collection: Collection) -> CollectionOut:
    papers, notes = (await org.collection_counts(db, [collection.id])).get(collection.id, (0, 0))
    return CollectionOut.model_validate(collection).model_copy(
        update={"paper_count": papers, "note_count": notes}
    )


@router.get("/collections", response_model=list[CollectionOut])
async def list_collections(user: CurrentUser, db: DbSession) -> list[CollectionOut]:
    collections = await org.list_collections(db, user.id)
    counts = await org.collection_counts(db, [c.id for c in collections])
    return [
        CollectionOut.model_validate(c).model_copy(
            update={"paper_count": counts[c.id][0], "note_count": counts[c.id][1]}
        )
        for c in collections
    ]


@router.post("/collections", response_model=CollectionOut, status_code=status.HTTP_201_CREATED)
async def create_collection(
    body: CollectionCreate, user: CurrentUser, db: DbSession
) -> CollectionOut:
    collection = Collection(
        user_id=user.id, name=body.name.strip(), description=body.description, kind=body.kind
    )
    db.add(collection)
    await db.flush()
    if body.document_ids:
        await org.add_to_collection(db, user.id, collection, body.document_ids)
        await db.flush()
    await db.refresh(collection)
    return await _collection_out(db, collection)


@router.get("/collections/{collection_id}", response_model=CollectionDetail)
async def get_collection(
    collection_id: uuid.UUID, user: CurrentUser, db: DbSession, documents: DocumentServiceDep
) -> CollectionDetail:
    collection = await org.get_collection(db, user.id, collection_id)
    ids = await org.collection_document_ids(db, collection.id)
    docs = await org.owned_documents(db, user.id, ids) if ids else []
    out = await _collection_out(db, collection)
    return CollectionDetail(**out.model_dump(), documents=await documents.summaries(docs))


@router.patch("/collections/{collection_id}", response_model=CollectionOut)
async def update_collection(
    collection_id: uuid.UUID, body: CollectionUpdate, user: CurrentUser, db: DbSession
) -> CollectionOut:
    collection = await org.get_collection(db, user.id, collection_id)
    if body.name is not None:
        collection.name = body.name.strip()
    if body.description is not None:
        collection.description = body.description
    if body.kind is not None:
        collection.kind = body.kind
    await db.flush()
    await db.refresh(collection)
    return await _collection_out(db, collection)


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(collection_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Deletes the collection and its notes; the papers stay in the library."""
    await db.delete(await org.get_collection(db, user.id, collection_id))


@router.post("/collections/{collection_id}/documents", response_model=AddedPapers)
async def add_papers(
    collection_id: uuid.UUID, body: CollectionPapers, user: CurrentUser, db: DbSession
) -> AddedPapers:
    collection = await org.get_collection(db, user.id, collection_id)
    added = await org.add_to_collection(db, user.id, collection, body.document_ids)
    await db.flush()
    count = len(await org.collection_document_ids(db, collection.id))
    return AddedPapers(added=added, paper_count=count)


@router.delete(
    "/collections/{collection_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_paper(
    collection_id: uuid.UUID, document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    collection = await org.get_collection(db, user.id, collection_id)
    await org.remove_from_collection(db, collection, document_id)


@router.get(
    "/collections/{collection_id}/export",
    summary="The collection's papers as BibTeX or RIS (Zotero, Mendeley, EndNote, Overleaf)",
)
async def export_collection(
    collection_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    format: Literal["bibtex", "ris"] = Query(default="bibtex"),
) -> Response:
    collection = await org.get_collection(db, user.id, collection_id)
    ids = await org.collection_document_ids(db, collection.id)
    references = await org.references_for(db, user.id, ids)
    body = bibtex(references) if format == "bibtex" else ris(references)
    extension, media = (
        ("bib", "application/x-bibtex")
        if format == "bibtex"
        else ("ris", "application/x-research-info-systems")
    )
    filename = (
        "".join(c if c.isalnum() else "-" for c in collection.name.lower()).strip("-")
        or "collection"
    )
    return Response(
        body,
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}.{extension}"'},
    )


# --- tags ----------------------------------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
async def list_tags(user: CurrentUser, db: DbSession) -> list[TagOut]:
    return [
        TagOut.model_validate(tag).model_copy(update={"paper_count": count})
        for tag, count in await org.list_tags(db, user.id)
    ]


@router.patch("/tags/{tag_id}", response_model=TagOut)
async def update_tag(
    tag_id: uuid.UUID, body: TagUpdate, user: CurrentUser, db: DbSession
) -> TagOut:
    tag = await org.get_tag(db, user.id, tag_id)
    await org.rename_tag(db, user.id, tag, body.name, body.color)
    await db.flush()
    return TagOut.model_validate(tag)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(tag_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Removes the tag from every paper."""
    await db.delete(await org.get_tag(db, user.id, tag_id))


# --- a paper's organization ----------------------------------------------------------------------


async def _organization(
    db: DbSession, user_id: uuid.UUID, document: Document
) -> DocumentOrganization:
    info = (await org.organization_info(db, user_id, [document.id]))[document.id]
    return DocumentOrganization(
        tags=info["tags"],
        reading_status=document.reading_status,
        bookmarked=info["bookmarked"],
        collections=await org.document_collections(db, document.id),
    )


@router.get("/documents/{document_id}/organization", response_model=DocumentOrganization)
async def document_organization(
    document_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> DocumentOrganization:
    return await _organization(db, user.id, await org.get_document(db, user.id, document_id))


@router.put("/documents/{document_id}/tags", response_model=DocumentOrganization)
async def set_tags(
    document_id: uuid.UUID, body: DocumentTagsIn, user: CurrentUser, db: DbSession
) -> DocumentOrganization:
    document = await org.get_document(db, user.id, document_id)
    await org.set_document_tags(db, user.id, document, body.names)
    await db.flush()
    return await _organization(db, user.id, document)


@router.put("/documents/{document_id}/reading-status", response_model=DocumentOrganization)
async def set_reading_status(
    document_id: uuid.UUID, body: ReadingStatusIn, user: CurrentUser, db: DbSession
) -> DocumentOrganization:
    document = await org.get_document(db, user.id, document_id)
    document.reading_status = body.status.value if body.status else None
    await db.flush()
    return await _organization(db, user.id, document)


# --- notes ---------------------------------------------------------------------------------------


async def _notes_out(db: DbSession, notes: list[Note]) -> list[NoteOut]:
    titles = await org.document_titles(db, {n.document_id for n in notes if n.document_id})
    return [
        NoteOut.model_validate(n).model_copy(
            update={
                "document_title": titles.get(n.document_id, (None, None))[0]
                if n.document_id
                else None
            }
        )
        for n in notes
    ]


@router.get("/notes", response_model=list[NoteOut])
async def list_notes(
    user: CurrentUser,
    db: DbSession,
    document_id: uuid.UUID | None = None,
    collection_id: uuid.UUID | None = None,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[NoteOut]:
    notes = await org.list_notes(
        db, user.id, document_id=document_id, collection_id=collection_id, limit=limit
    )
    return await _notes_out(db, notes)


@router.post("/notes", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(body: NoteCreate, user: CurrentUser, db: DbSession) -> NoteOut:
    if body.document_id is None and body.collection_id is None:
        raise ValidationError("A note belongs to a paper or a collection.")
    if body.document_id is not None:
        await org.get_document(db, user.id, body.document_id)
    if body.collection_id is not None:
        await org.get_collection(db, user.id, body.collection_id)
    anchor = body.anchor.model_dump(mode="json", exclude_none=True) if body.anchor else None
    note = Note(
        user_id=user.id,
        document_id=body.document_id,
        collection_id=body.collection_id,
        anchor=anchor,
        content=body.content,
    )
    db.add(note)
    await db.flush()
    await db.refresh(note)
    return (await _notes_out(db, [note]))[0]


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: uuid.UUID, body: NoteUpdate, user: CurrentUser, db: DbSession
) -> NoteOut:
    note = await org.get_note(db, user.id, note_id)
    note.content = body.content
    await db.flush()
    await db.refresh(note)
    return (await _notes_out(db, [note]))[0]


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await org.get_note(db, user.id, note_id))


# --- bookmarks -----------------------------------------------------------------------------------


async def _bookmarks_out(db: DbSession, bookmarks: list[Bookmark]) -> list[BookmarkOut]:
    titles = await org.document_titles(db, {b.document_id for b in bookmarks})
    return [
        BookmarkOut.model_validate(b).model_copy(
            update={
                "document_title": titles.get(b.document_id, (None, None))[0],
                "document_year": titles.get(b.document_id, (None, None))[1],
            }
        )
        for b in bookmarks
    ]


@router.get("/bookmarks", response_model=list[BookmarkOut])
async def list_bookmarks(
    user: CurrentUser,
    db: DbSession,
    document_id: uuid.UUID | None = None,
    kind: list[str] | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500),
) -> list[BookmarkOut]:
    bookmarks = await org.list_bookmarks(
        db, user.id, document_id=document_id, kinds=kind, limit=limit
    )
    return await _bookmarks_out(db, bookmarks)


@router.post("/bookmarks", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
async def create_bookmark(body: BookmarkCreate, user: CurrentUser, db: DbSession) -> BookmarkOut:
    """Idempotent: bookmarking the same paper / passage / element again returns the existing one."""
    await org.get_document(db, user.id, body.document_id)
    target = body.target.model_dump(mode="json", exclude_none=True)
    key = org.bookmark_key(body.document_id, body.kind, target)
    existing = await db.scalar(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.key == key)
    )
    if existing is None:
        existing = Bookmark(
            user_id=user.id,
            document_id=body.document_id,
            kind=body.kind,
            target=target,
            label=body.label,
            key=key,
        )
        db.add(existing)
        await db.flush()
        await db.refresh(existing)
    return (await _bookmarks_out(db, [existing]))[0]


@router.delete("/bookmarks/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_bookmark(bookmark_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    await db.delete(await org.get_bookmark(db, user.id, bookmark_id))


@router.delete("/documents/{document_id}/bookmark", status_code=status.HTTP_204_NO_CONTENT)
async def unbookmark_paper(document_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """Remove the paper-level bookmark (passage bookmarks stay)."""
    await org.get_document(db, user.id, document_id)  # 404 for someone else's paper
    key = org.bookmark_key(document_id, "paper", {})
    bookmark = await db.scalar(
        select(Bookmark).where(Bookmark.user_id == user.id, Bookmark.key == key)
    )
    if bookmark is not None:
        await db.delete(bookmark)
