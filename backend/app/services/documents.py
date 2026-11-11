"""Document use-cases: upload, versioning, listing, correction, duplicates, deletion."""

from __future__ import annotations

import asyncio
import difflib
import io
import tempfile
import uuid
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, cast

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.database import after_commit
from app.core.errors import AppError, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.signing import sign_scope
from app.models.document import (
    Document,
    DocumentMetadata,
    DocumentStatus,
    DocumentVersion,
    DuplicateKind,
    IndexStatus,
)
from app.models.job import Job, JobStatus
from app.repositories.documents import DocumentRepository, SortKey
from app.schemas.document import (
    Author,
    DocumentAssets,
    DocumentDetail,
    DocumentSummary,
    DuplicateInfo,
    MetadataResponse,
    MetadataUpdate,
    ProcessingProgress,
    TagRef,
    VersionResponse,
)
from app.services import arxiv, zip_import
from app.services import doi as doi_lookup
from app.services.audit import record_audit
from app.services.indexing import remove_from_index
from app.services.ingestion.cleaning import normalize_title
from app.services.ingestion.validation import validate_upload
from app.services.jobs import JobService
from app.services.organization import organization_info
from app.services.storage import FileStorage, sha256_file, storage_key

log = get_logger(__name__)

PROCESS_JOB = "document.process"
INDEX_JOB = "document.index"
_CHUNK = 1024 * 1024
TITLE_SIMILARITY_THRESHOLD = 0.9


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    kind: DuplicateKind
    document_id: uuid.UUID


def find_duplicate(
    *,
    file_match: uuid.UUID | None,
    metadata: DocumentMetadata | None,
    candidates: list[tuple[uuid.UUID, DocumentMetadata]],
) -> DuplicateMatch | None:
    """Classify the strongest duplicate signal. Never rejects: the user decides."""
    if file_match is not None:
        return DuplicateMatch(DuplicateKind.EXACT, file_match)
    if metadata is None:
        return None
    for document_id, other in candidates:
        if metadata.doi and other.doi and metadata.doi.lower() == other.doi.lower():
            return DuplicateMatch(DuplicateKind.PROBABLE, document_id)
        if metadata.arxiv_id and other.arxiv_id and metadata.arxiv_id == other.arxiv_id:
            return DuplicateMatch(DuplicateKind.PROBABLE, document_id)
    title = metadata.normalized_title or ""
    if len(title) < 12:  # short titles ("Notes") are too ambiguous to compare
        return None
    best: tuple[float, uuid.UUID] | None = None
    for document_id, other in candidates:
        other_title = other.normalized_title or ""
        if not other_title:
            continue
        if other_title == title:
            return DuplicateMatch(DuplicateKind.PROBABLE, document_id)
        ratio = difflib.SequenceMatcher(None, title, other_title).ratio()
        if ratio >= TITLE_SIMILARITY_THRESHOLD and (best is None or ratio > best[0]):
            best = (ratio, document_id)
    return DuplicateMatch(DuplicateKind.POSSIBLE, best[1]) if best else None


def authors_display(authors: list[dict[str, Any]]) -> str:
    names = [str(a.get("name", "")).strip() for a in authors if a.get("name")]
    if not names:
        return ""
    if len(names) <= 3:
        return ", ".join(names)
    return f"{names[0]}, {names[1]}, … +{len(names) - 2}"


class DocumentService:
    def __init__(
        self, session: AsyncSession, settings: Settings, storage: FileStorage, jobs: JobService
    ) -> None:
        self.session = session
        self.settings = settings
        self.storage = storage
        self.jobs = jobs
        self.repo = DocumentRepository(session)

    # --- upload ------------------------------------------------------------------------

    async def _spool(self, upload: UploadFile, limit_mb: int | None = None) -> Path:
        """Stream the upload to a temp file, enforcing the size limit while reading."""
        limit_mb = limit_mb or self.settings.max_upload_size_mb
        limit = limit_mb * 1024 * 1024
        tmp_dir = self.settings.storage_dir / "tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=tmp_dir, delete=False)  # noqa: SIM115
        size = 0
        try:
            with handle:
                while chunk := await upload.read(_CHUNK):
                    size += len(chunk)
                    if size > limit:
                        raise ValidationError(
                            f"“{upload.filename}” is larger than the {limit_mb} MB limit.",
                            hint="Try a compressed version of the file.",
                        )
                    handle.write(chunk)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)  # noqa: ASYNC240
            raise
        return Path(handle.name)

    async def upload(self, user_id: uuid.UUID, upload: UploadFile) -> Document:
        path = await self._spool(upload)
        try:
            validated = validate_upload(
                path, upload.filename or "document", self.settings.max_upload_size_mb * 1024**2
            )
            file_hash = sha256_file(path)
            document = Document(
                user_id=user_id,
                title=Path(validated.filename).stem[:500] or "Untitled",
                doc_type=validated.format.value,
                original_filename=validated.filename,
                status=DocumentStatus.QUEUED,
            )
            self.session.add(document)
            await self.session.flush()
            version = await self._create_version(document, validated, path, file_hash, 1)
            exact = await self.repo.find_version_by_hash(user_id, file_hash, document.id)
            if exact is not None:
                document.duplicate_kind = DuplicateKind.EXACT.value
                document.duplicate_of_id = exact.document_id
            await self._enqueue(document, version)
            await record_audit(
                self.session,
                "document.upload",
                user_id=user_id,
                resource_type="document",
                resource_id=str(document.id),
                details={"filename": validated.filename, "size": validated.size},
            )
            return document
        finally:
            path.unlink(missing_ok=True)

    async def import_arxiv(self, user_id: uuid.UUID, reference: str) -> Document:
        """Fetch a paper from arXiv and add it like an upload, with arXiv's own metadata."""
        arxiv_id, _ = arxiv.parse_reference(reference)
        existing = await self.session.scalar(
            select(DocumentMetadata.arxiv_id).where(
                DocumentMetadata.user_id == user_id, DocumentMetadata.arxiv_id == arxiv_id
            )
        )
        if existing is not None:
            raise ConflictError(
                f"arXiv:{arxiv_id} is already in your library.",
                hint="Open it from the Papers page.",
            )
        paper = await arxiv.fetch(self.settings, reference)
        document = await self.upload(
            user_id, UploadFile(file=io.BytesIO(paper.pdf), filename=paper.filename)
        )
        await self._apply_external_metadata(
            user_id,
            document,
            "arxiv",
            title=paper.title,
            authors=[Author(**a) for a in paper.authors],
            abstract=paper.abstract,
            year=paper.year,
            publication_date=paper.published,
            doi=paper.doi,
            arxiv_id=paper.arxiv_id,
        )
        return document

    async def _apply_external_metadata(
        self, user_id: uuid.UUID, document: Document, source: str, **fields: Any
    ) -> DocumentDetail:
        """Metadata from an authoritative service. Protected from reprocessing like a user's
        corrections, but its provenance says where it came from."""
        patch = MetadataUpdate(**{k: v for k, v in fields.items() if v})  # only what it gave
        detail = await self.update_metadata(user_id, document.id, patch)
        version = await self.current_version(document)
        assert version is not None
        metadata = await self.repo.get_metadata(version.id)
        assert metadata is not None
        metadata.provenance = {
            **(metadata.provenance or {}),
            **{field: {"source": source, "confidence": "high"} for field in patch.model_fields_set},
        }
        return detail

    async def import_zip(
        self, user_id: uuid.UUID, upload: UploadFile
    ) -> tuple[list[Document], list[tuple[str, AppError]], list[zip_import.Skipped]]:
        """Every supported paper in a .zip, each through the normal upload path. Returns what was
        added, what failed (with the reason) and what was left out (with the reason)."""
        path = await self._spool(upload, self.settings.max_zip_size_mb)
        try:
            if not zipfile.is_zipfile(path):
                raise ValidationError(
                    "This isn't a valid zip file.", hint="Compress the papers into a .zip first."
                )
            per_file = self.settings.max_upload_size_mb * 1024 * 1024
            budget = zip_import.Budget(per_file * zip_import.TOTAL_FACTOR)
            documents: list[Document] = []
            errors: list[tuple[str, AppError]] = []
            with zipfile.ZipFile(path) as archive:
                entries, skipped = zip_import.plan(archive, per_file)
                if len(entries) > zip_import.MAX_ENTRIES:
                    raise ValidationError(
                        f"The archive holds {len(entries)} papers; the limit is "
                        f"{zip_import.MAX_ENTRIES} at a time.",
                        hint="Split it into smaller zips.",
                    )
                if not entries:
                    raise ValidationError(
                        "No papers were found in this zip.",
                        hint="It needs PDF, DOCX, HTML, Markdown or text files.",
                    )
                for info in entries:
                    name = zip_import.display_name(info.filename)
                    data = await asyncio.to_thread(
                        zip_import.read_entry, archive, info, per_file, budget
                    )
                    if isinstance(data, str):
                        skipped.append(zip_import.Skipped(name, data))
                        continue
                    try:
                        documents.append(
                            await self.upload(
                                user_id, UploadFile(file=cast(BinaryIO, data), filename=name)
                            )
                        )
                    except AppError as exc:
                        errors.append((name, exc))
                    finally:
                        data.close()
            await record_audit(
                self.session,
                "document.zip_import",
                user_id=user_id,
                details={
                    "imported": len(documents),
                    "failed": len(errors),
                    "skipped": len(skipped),
                },
            )
            return documents, errors, skipped
        finally:
            path.unlink(missing_ok=True)

    async def import_reference(self, user_id: uuid.UUID, reference: str) -> Document:
        """An arXiv id / link, or a DOI. arXiv DOIs import in full; other DOIs have no PDF to
        fetch, so the answer says what was found and what to do instead."""
        kind, value = doi_lookup.classify(reference)
        if kind == "arxiv":
            return await self.import_arxiv(user_id, value)
        record = await doi_lookup.fetch(self.settings, value)
        raise ConflictError(
            f"“{record.title[:120]}” can't be downloaded from its DOI.",
            hint="Upload the PDF, then use “Fill from DOI” on the paper to correct its metadata.",
        )

    async def apply_doi(
        self, user_id: uuid.UUID, document_id: uuid.UUID, reference: str
    ) -> DocumentDetail:
        """Fill a paper's title, authors, abstract, date, venue and DOI from Crossref."""
        document = await self.get(user_id, document_id)
        record = await doi_lookup.fetch(self.settings, reference)
        return await self._apply_external_metadata(
            user_id,
            document,
            "crossref",
            title=record.title,
            authors=[Author(**a) for a in record.authors],
            abstract=record.abstract,
            year=record.year,
            publication_date=record.published,
            venue=record.venue,
            doi=record.doi,
        )

    async def add_version(
        self, user_id: uuid.UUID, document_id: uuid.UUID, upload: UploadFile
    ) -> Document:
        document = await self.get(user_id, document_id)
        path = await self._spool(upload)
        try:
            validated = validate_upload(
                path, upload.filename or "document", self.settings.max_upload_size_mb * 1024**2
            )
            file_hash = sha256_file(path)
            versions = await self.repo.list_versions(document.id)
            if any(v.file_hash == file_hash for v in versions):
                raise ConflictError(
                    "This exact file is already a version of this paper.",
                    hint="Upload the modified file instead.",
                )
            number = max(v.version_number for v in versions) + 1
            version = await self._create_version(document, validated, path, file_hash, number)
            document.doc_type = validated.format.value
            document.original_filename = validated.filename
            await self._enqueue(document, version)
            await record_audit(
                self.session,
                "document.version_added",
                user_id=user_id,
                resource_type="document",
                resource_id=str(document.id),
                details={"version": number},
            )
            return document
        finally:
            path.unlink(missing_ok=True)

    async def _create_version(
        self, document: Document, validated: Any, path: Path, file_hash: str, number: int
    ) -> DocumentVersion:
        version_id = uuid.uuid4()
        key = storage_key(document.user_id, version_id, Path(validated.filename).suffix.lower())
        self.storage.save(path, key)
        version = DocumentVersion(
            id=version_id,
            document_id=document.id,
            user_id=document.user_id,
            version_number=number,
            storage_key=key,
            file_hash=file_hash,
            file_size=validated.size,
            mime_type=validated.mime_type,
            original_filename=validated.filename,
        )
        self.session.add(version)
        await self.session.flush()
        document.current_version_id = version.id
        return version

    async def _enqueue(self, document: Document, version: DocumentVersion) -> None:
        document.status = DocumentStatus.QUEUED
        document.error_message = None
        document.index_status = IndexStatus.PENDING
        document.index_error = None
        job = await self.jobs.enqueue(
            document.user_id,
            PROCESS_JOB,
            payload={"version_id": str(version.id)},
            subject_type="document",
            subject_id=document.id,
        )
        document.processing_job_id = job.id

    # --- queries ---------------------------------------------------------------------------

    async def get(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.repo.get_for_user(document_id, user_id)
        if document is None:
            raise NotFoundError("We couldn't find that paper.", hint="It may have been deleted.")
        return document

    async def list(
        self,
        user_id: uuid.UUID,
        *,
        query: str | None,
        statuses: list[DocumentStatus] | None,
        sort: SortKey,
        limit: int,
        offset: int,
        only: set[uuid.UUID] | None = None,
        reading_status: str | None = None,
        bookmarked: bool | None = None,
    ) -> tuple[list[DocumentSummary], int]:
        documents, total = await self.repo.list_for_user(
            user_id,
            query=query,
            statuses=statuses,
            sort=sort,
            limit=limit,
            offset=offset,
            only=only,
            reading_status=reading_status,
            bookmarked=bookmarked,
        )
        return await self.summaries(documents), total

    async def summaries(self, documents: Sequence[Document]) -> list[DocumentSummary]:
        """Summaries with tags / bookmark state fetched once for the whole page."""
        if not documents:
            return []
        info = await organization_info(
            self.session, documents[0].user_id, [d.id for d in documents]
        )
        return [await self.summary(d, info[d.id]) for d in documents]

    async def current_version(self, document: Document) -> DocumentVersion | None:
        if document.current_version_id is None:
            return None
        return await self.repo.get_version(document.current_version_id)

    async def assets(self, document: Document) -> DocumentAssets | None:
        version = await self.current_version(document)
        if version is None:
            return None
        signature = sign_scope(f"version:{version.id}", self.settings)
        base = f"{self.settings.api_prefix}/assets/versions/{version.id}"
        is_pdf = document.doc_type == "pdf"
        return DocumentAssets(
            thumbnail=f"{base}/thumbnail.png?{signature}" if version.has_thumbnail else None,
            file=f"{base}/file?{signature}",
            page_template=f"{base}/pages/{{page}}.png?w={{width}}&{signature}" if is_pdf else None,
        )

    async def _progress(self, document: Document) -> ProcessingProgress | None:
        if document.processing_job_id is None:
            return None
        job = await self.session.get(Job, document.processing_job_id)
        if job is None:
            return None
        # Ready papers only report progress while a (re-)indexing job is active.
        if document.status == DocumentStatus.READY and job.status not in (
            JobStatus.QUEUED,
            JobStatus.RUNNING,
        ):
            return None
        return ProcessingProgress(
            job_id=job.id,
            status=job.status,
            stage=job.stage,
            stage_detail=job.stage_detail,
            progress=job.progress,
            started_at=job.started_at,
            error_message=job.error_message if job.status == JobStatus.FAILED else None,
        )

    async def summary(
        self, document: Document, organization: dict[str, Any] | None = None
    ) -> DocumentSummary:
        metadata = (
            await self.repo.get_metadata(document.current_version_id)
            if document.current_version_id
            else None
        )
        result = DocumentSummary.model_validate(document)
        result.venue = metadata.venue if metadata else None
        result.assets = await self.assets(document)
        result.processing = await self._progress(document)
        if organization is None:
            organization = (await organization_info(self.session, document.user_id, [document.id]))[
                document.id
            ]
        result.tags = [TagRef(**t) for t in organization["tags"]]
        result.bookmarked = organization["bookmarked"]
        return result

    async def detail(self, user_id: uuid.UUID, document_id: uuid.UUID) -> DocumentDetail:
        document = await self.get(user_id, document_id)
        summary = await self.summary(document)
        version = await self.current_version(document)
        metadata = await self.repo.get_metadata(version.id) if version else None
        versions = await self.repo.list_versions(document.id)
        duplicate_of = None
        if document.duplicate_of_id and document.duplicate_kind:
            other = await self.repo.get_for_user(document.duplicate_of_id, user_id)
            if other is not None:
                duplicate_of = DuplicateInfo(
                    kind=document.duplicate_kind, document_id=other.id, title=other.title
                )
        return DocumentDetail(
            **summary.model_dump(),
            metadata=MetadataResponse.model_validate(metadata) if metadata else None,
            version=VersionResponse.model_validate(version) if version else None,
            version_count=len(versions),
            duplicate_of=duplicate_of,
        )

    async def mark_opened(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get(user_id, document_id)
        document.last_opened_at = datetime.now(UTC)

    # --- mutations ----------------------------------------------------------------------------

    async def update_metadata(
        self, user_id: uuid.UUID, document_id: uuid.UUID, patch: MetadataUpdate
    ) -> DocumentDetail:
        document = await self.get(user_id, document_id)
        version = await self.current_version(document)
        if version is None:
            raise ConflictError("This paper has no processed version yet.")
        metadata = await self.repo.get_metadata(version.id)
        if metadata is None:
            metadata = DocumentMetadata(version_id=version.id, user_id=user_id)
            self.session.add(metadata)
        changes = patch.model_dump(exclude_unset=True)
        if not changes:
            raise ValidationError("Nothing to update.")
        for field, value in changes.items():
            setattr(metadata, field, value)
            metadata.provenance = {
                **(metadata.provenance or {}),
                field: {"source": "user", "confidence": "high"},
            }
        metadata.user_corrected_fields = sorted(
            set(metadata.user_corrected_fields or []) | set(changes)
        )
        if "title" in changes:
            metadata.normalized_title = normalize_title(changes["title"])
            document.title = changes["title"]
            document.title_is_user_set = True
        if "year" in changes:
            document.year = changes["year"]
        if "authors" in changes:
            document.authors_display = authors_display(changes["authors"])
        await record_audit(
            self.session,
            "document.metadata_corrected",
            user_id=user_id,
            resource_type="document",
            resource_id=str(document.id),
            details={"fields": sorted(changes)},
        )
        await self.session.flush()
        return await self.detail(user_id, document_id)

    async def reprocess(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        document = await self.get(user_id, document_id)
        if self.settings.demo_mode and document.user_id == self.settings.demo_user_id:
            raise PermissionDeniedError("Shared sample papers are read-only in the public demo.")
        if document.status in (DocumentStatus.QUEUED, DocumentStatus.PROCESSING):
            raise ConflictError("This paper is already being processed.")
        version = await self.current_version(document)
        if version is None:
            raise ConflictError("This paper has no file to process.")
        await self._enqueue(document, version)
        return document

    async def reindex(self, user_id: uuid.UUID, document_id: uuid.UUID) -> Document:
        """Re-run search indexing only (e.g. after an embedding failure)."""
        document = await self.get(user_id, document_id)
        version = await self.current_version(document)
        if document.status != DocumentStatus.READY or version is None:
            raise ConflictError("The paper must finish processing before it can be indexed.")
        document.index_status = IndexStatus.PENDING
        document.index_error = None
        job = await self.jobs.enqueue(
            user_id,
            INDEX_JOB,
            payload={"version_id": str(version.id)},
            subject_type="document",
            subject_id=document.id,
        )
        document.processing_job_id = job.id
        return document

    async def delete(self, user_id: uuid.UUID, document_id: uuid.UUID) -> None:
        document = await self.get(user_id, document_id)
        if self.settings.demo_mode and document.user_id == self.settings.demo_user_id:
            raise PermissionDeniedError("Shared sample papers cannot be deleted in the public demo.")
        versions = await self.repo.list_versions(document.id)
        keys = [v.storage_key for v in versions]
        version_ids = [v.id for v in versions]
        index_records = [
            {"embedding_model": v.embedding_model, "embedding_dimension": v.embedding_dimension}
            for v in versions
        ]
        settings = self.settings
        document.current_version_id = None
        await self.session.flush()
        await self.session.delete(document)
        await record_audit(
            self.session,
            "document.deleted",
            user_id=user_id,
            resource_type="document",
            resource_id=str(document_id),
        )

        def remove_files() -> None:  # only once the rows are really gone
            for key in keys:
                self.storage.delete(key)
            for version_id in version_ids:
                self.storage.delete_derived(version_id)
            try:
                remove_from_index(settings, document_id, index_records)
            except Exception as exc:  # index cleanup must not undo a completed delete
                log.warning("vector_cleanup_failed", document_id=str(document_id), error=repr(exc))

        after_commit(self.session, remove_files)

    async def resolve_duplicate(
        self, user_id: uuid.UUID, document_id: uuid.UUID, action: str
    ) -> Document | None:
        document = await self.get(user_id, document_id)
        if document.duplicate_of_id is None:
            raise ConflictError("This paper isn't marked as a duplicate.")
        original_id = document.duplicate_of_id
        if action == "keep_both":
            document.duplicate_kind = None
            document.duplicate_of_id = None
            return document
        if action == "delete":
            await self.delete(user_id, document_id)
            return None
        # merge_as_version: move this upload under the original as its newest version.
        original = await self.get(user_id, original_id)
        version = await self.current_version(document)
        if version is None:
            raise ConflictError("This paper has no file to merge.")
        existing = await self.repo.list_versions(original.id)
        version.document_id = original.id
        version.version_number = max(v.version_number for v in existing) + 1
        original.current_version_id = version.id
        original.status = document.status
        original.page_count = document.page_count
        original.processing_job_id = document.processing_job_id
        if not original.title_is_user_set:
            original.title = document.title
        document.current_version_id = None
        await self.session.flush()
        await self.session.delete(document)  # files now belong to the original
        # The moved version's vectors carry the old document id: re-index under the original.
        if original.status == DocumentStatus.READY:
            original.index_status = IndexStatus.PENDING
            await self.jobs.enqueue(
                user_id,
                INDEX_JOB,
                payload={"version_id": str(version.id)},
                subject_type="document",
                subject_id=original.id,
            )
        await record_audit(
            self.session,
            "document.merged_as_version",
            user_id=user_id,
            resource_type="document",
            resource_id=str(original.id),
            details={"merged_document": str(document_id), "version": version.version_number},
        )
        return original
