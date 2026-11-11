from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep, SettingsDep
from app.core.errors import AppError, PermissionDeniedError
from app.models.document import Chunk, DocumentStatus
from app.models.organization import Collection, CollectionKind
from app.repositories.documents import DocumentRepository, SortKey
from app.schemas.common import ErrorResponse, Page
from app.schemas.document import (
    ChunkOut,
    DocumentDetail,
    DocumentStructureResponse,
    DocumentSummary,
    DoiRequest,
    DuplicateResolution,
    ElementOut,
    ImportRequest,
    LibraryStats,
    MetadataUpdate,
    PageOut,
    ReferenceOut,
    SectionOut,
    SimilarPaperOut,
    SimilarPapersResponse,
    SkippedFile,
    UploadError,
    UploadResponse,
    VersionResponse,
    ZipImportResponse,
)
from app.services import organization as org
from app.services.organization import documents_matching
from app.services.similarity import similar_documents

router = APIRouter(prefix="/documents", tags=["documents"])

MAX_FILES_PER_REQUEST = 50


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload one or more documents",
    description="Each file is validated independently: valid files are queued for processing "
    "even if others in the same request are rejected.",
)
async def upload_documents(
    user: CurrentUser,
    documents: DocumentServiceDep,
    files: Annotated[list[UploadFile], File(description="PDF, DOCX, TXT, Markdown or HTML")],
) -> UploadResponse:
    if documents.settings.demo_mode or not documents.settings.uploads_enabled:
        raise PermissionDeniedError(
            "Document uploads and custom research libraries are available in the full self-hosted version. "
            "Visit our GitHub repository to run Research Intelligence locally.",
            hint=documents.settings.github_url,
        )
    if len(files) > MAX_FILES_PER_REQUEST:
        raise AppError(
            f"You can upload up to {MAX_FILES_PER_REQUEST} files at once.",
            hint="Split the upload into smaller batches.",
        )
    items: list[DocumentSummary] = []
    errors: list[UploadError] = []
    for upload in files:
        try:
            document = await documents.upload(user.id, upload)
            items.append(await documents.summary(document))
        except AppError as exc:
            errors.append(
                UploadError(filename=upload.filename or "file", message=exc.message, hint=exc.hint)
            )
    if not items and errors:
        raise AppError(
            errors[0].message if len(errors) == 1 else "None of the files could be uploaded.",
            hint=errors[0].hint,
            details={"errors": [e.model_dump() for e in errors]},
        )
    return UploadResponse(items=items, errors=errors)


@router.post(
    "/import/zip",
    response_model=ZipImportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import a folder of papers as a .zip",
    description="Every PDF, DOCX, HTML, Markdown or text file in the archive is added like an "
    "upload. Files that were left out come back with the reason. With `collection_name` the "
    "imported papers are also put into a new collection (a ready-made project library).",
)
async def import_zip(
    user: CurrentUser,
    db: DbSession,
    documents: DocumentServiceDep,
    file: Annotated[UploadFile, File(description="A .zip of papers")],
    collection_name: Annotated[str | None, Query(max_length=120)] = None,
) -> ZipImportResponse:
    if documents.settings.demo_mode or not documents.settings.uploads_enabled:
        raise PermissionDeniedError(
            "Document uploads and custom research libraries are available in the full self-hosted version. "
            "Visit our GitHub repository to run Research Intelligence locally.",
            hint=documents.settings.github_url,
        )
    added, failed, skipped = await documents.import_zip(user.id, file)
    items = [await documents.summary(d) for d in added]
    collection_id = None
    name = (collection_name or "").strip()
    if name and added:
        collection = Collection(
            user_id=user.id, name=name, description="", kind=CollectionKind.PROJECT
        )
        db.add(collection)
        await db.flush()
        await org.add_to_collection(db, user.id, collection, [d.id for d in added])
        collection_id = collection.id
    return ZipImportResponse(
        items=items,
        errors=[UploadError(filename=n, message=e.message, hint=e.hint) for n, e in failed],
        skipped=[SkippedFile(filename=s.filename, reason=s.reason) for s in skipped],
        collection_id=collection_id,
    )


@router.post(
    "/import",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Import papers from arXiv (id or link) or by arXiv DOI",
    description="Fetches the PDF and arXiv's own title, authors, abstract and date. A DOI that "
    "isn't an arXiv paper has no PDF to fetch and is answered with what to do instead. Each "
    "paper succeeds or fails on its own.",
)
async def import_papers(
    body: ImportRequest, user: CurrentUser, documents: DocumentServiceDep
) -> UploadResponse:
    items: list[DocumentSummary] = []
    errors: list[UploadError] = []
    for ref in dict.fromkeys(r.strip() for r in body.refs if r.strip()):
        try:
            items.append(await documents.summary(await documents.import_reference(user.id, ref)))
        except AppError as exc:
            errors.append(UploadError(filename=ref, message=exc.message, hint=exc.hint))
    if not items and errors:
        raise AppError(
            errors[0].message if len(errors) == 1 else "None of the papers could be imported.",
            hint=errors[0].hint,
            details={"errors": [e.model_dump() for e in errors]},
        )
    return UploadResponse(items=items, errors=errors)


@router.get("", response_model=Page[DocumentSummary], summary="List the paper library")
async def list_documents(
    user: CurrentUser,
    documents: DocumentServiceDep,
    db: DbSession,
    q: str | None = Query(default=None, max_length=200, description="Title / author / filename"),
    status_filter: list[DocumentStatus] | None = Query(default=None, alias="status"),
    sort: SortKey = "recent",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    collection_id: uuid.UUID | None = Query(default=None, description="Only this collection"),
    tag: list[str] | None = Query(default=None, description="Papers with any of these tags"),
    reading_status: str | None = Query(
        default=None, pattern="^(to_read|reading|done|none)$", description="none = not set"
    ),
    bookmarked: bool | None = Query(default=None),
) -> Page[DocumentSummary]:
    only = await documents_matching(
        db, user.id, collection_ids=[collection_id] if collection_id else None, tags=tag
    )
    items, total = await documents.list(
        user.id,
        query=q,
        statuses=status_filter,
        sort=sort,
        limit=limit,
        offset=offset,
        only=only,
        reading_status=reading_status,
        bookmarked=bookmarked,
    )
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/stats", response_model=LibraryStats)
async def library_stats(user: CurrentUser, db: DbSession) -> LibraryStats:
    repo = DocumentRepository(db)
    counts = await repo.status_counts(user.id)
    return LibraryStats(
        total=sum(counts.values()),
        ready=counts.get(DocumentStatus.READY, 0),
        processing=counts.get(DocumentStatus.QUEUED, 0) + counts.get(DocumentStatus.PROCESSING, 0),
        failed=counts.get(DocumentStatus.FAILED, 0),
        duplicates=await repo.pending_duplicates(user.id),
    )


@router.get(
    "/{document_id}", response_model=DocumentDetail, responses={404: {"model": ErrorResponse}}
)
async def get_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentDetail:
    return await documents.detail(user.id, document_id)


@router.get("/{document_id}/status", summary="Processing status (lightweight, for polling)")
async def document_status(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentSummary:
    return await documents.summary(await documents.get(user.id, document_id))


@router.post("/{document_id}/opened", status_code=status.HTTP_204_NO_CONTENT)
async def mark_opened(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> None:
    await documents.mark_opened(user.id, document_id)


@router.patch("/{document_id}/metadata", response_model=DocumentDetail)
async def update_metadata(
    document_id: uuid.UUID,
    body: MetadataUpdate,
    user: CurrentUser,
    documents: DocumentServiceDep,
) -> DocumentDetail:
    return await documents.update_metadata(user.id, document_id, body)


@router.post(
    "/{document_id}/metadata/doi",
    response_model=DocumentDetail,
    summary="Fill the paper's metadata from its DOI (Crossref)",
)
async def fill_from_doi(
    document_id: uuid.UUID,
    body: DoiRequest,
    user: CurrentUser,
    documents: DocumentServiceDep,
) -> DocumentDetail:
    return await documents.apply_doi(user.id, document_id, body.doi)


@router.post("/{document_id}/process", response_model=DocumentSummary, summary="Reprocess")
async def reprocess(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentSummary:
    return await documents.summary(await documents.reprocess(user.id, document_id))


@router.post(
    "/{document_id}/versions",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a new version of this paper",
)
async def add_version(
    document_id: uuid.UUID,
    user: CurrentUser,
    documents: DocumentServiceDep,
    file: Annotated[UploadFile, File()],
) -> DocumentSummary:
    return await documents.summary(await documents.add_version(user.id, document_id, file))


@router.get("/{document_id}/versions", response_model=list[VersionResponse])
async def list_versions(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep, db: DbSession
) -> list[VersionResponse]:
    document = await documents.get(user.id, document_id)
    versions = await DocumentRepository(db).list_versions(document.id)
    return [VersionResponse.model_validate(v) for v in reversed(versions)]


@router.post("/{document_id}/duplicate-resolution", response_model=DocumentSummary | None)
async def resolve_duplicate(
    document_id: uuid.UUID,
    body: DuplicateResolution,
    user: CurrentUser,
    documents: DocumentServiceDep,
    response: Response,
) -> DocumentSummary | None:
    result = await documents.resolve_duplicate(user.id, document_id, body.action)
    if result is None:
        response.status_code = status.HTTP_204_NO_CONTENT
        return None
    return await documents.summary(result)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> None:
    await documents.delete(user.id, document_id)


@router.post("/{document_id}/reindex", response_model=DocumentSummary, summary="Re-run indexing")
async def reindex(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep
) -> DocumentSummary:
    return await documents.summary(await documents.reindex(user.id, document_id))


@router.get(
    "/{document_id}/chunks",
    response_model=Page[ChunkOut],
    summary="Indexed passages (retrieval units) of the current version",
)
async def list_chunks(
    document_id: uuid.UUID,
    user: CurrentUser,
    documents: DocumentServiceDep,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Page[ChunkOut]:
    document = await documents.get(user.id, document_id)
    base = select(Chunk).where(Chunk.version_id == document.current_version_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery()))
    rows = await db.execute(base.order_by(Chunk.chunk_index).limit(limit).offset(offset))
    return Page(
        items=[ChunkOut.model_validate(c) for c in rows.scalars()],
        total=int(total or 0),
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}/similar", response_model=SimilarPapersResponse)
async def similar(
    document_id: uuid.UUID,
    user: CurrentUser,
    documents: DocumentServiceDep,
    db: DbSession,
    settings: SettingsDep,
    limit: int = Query(default=6, ge=1, le=20),
) -> SimilarPapersResponse:
    document = await documents.get(user.id, document_id)
    status_, results = await similar_documents(db, settings, user.id, document, limit)
    items = []
    for result in results:
        other = await documents.get(user.id, result.document_id)
        items.append(
            SimilarPaperOut(
                document=await documents.summary(other), score=result.score, reasons=result.reasons
            )
        )
    return SimilarPapersResponse(status=status_, items=items)


@router.get("/{document_id}/structure", response_model=DocumentStructureResponse)
async def document_structure(
    document_id: uuid.UUID, user: CurrentUser, documents: DocumentServiceDep, db: DbSession
) -> DocumentStructureResponse:
    """Sections (with paragraph anchors), pages, figures/tables/equations and references."""
    document = await documents.get(user.id, document_id)
    version = await documents.current_version(document)
    if version is None or version.processed_at is None:
        raise AppError("This paper hasn't finished processing yet.", hint="Try again in a moment.")
    repo = DocumentRepository(db)
    return DocumentStructureResponse(
        version_id=version.id,
        paginated=version.paginated,
        pages=[PageOut.model_validate(p) for p in await repo.pages(version.id)],
        sections=[SectionOut.model_validate(s) for s in await repo.sections(version.id)],
        elements=[ElementOut.model_validate(e) for e in await repo.elements(version.id)],
        references=[ReferenceOut.model_validate(r) for r in await repo.references(version.id)],
    )
