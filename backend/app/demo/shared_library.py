"""Shared sample research library management for the public demo.

Ensures that the 3 genuine open-access research papers are pre-indexed under the
shared DEMO_USER_ID, so demo visitors immediately have access to a populated
research library without duplicating data for every user or consuming upload quota.

On ephemeral filesystems (e.g. Render free tier) the container restarts discard
local files. The bootstrap packages the source PDFs in `backend/app/demo/papers/`
and automatically restores any missing files to disk and re-enqueues failed
processing jobs on cold starts.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.database import run_after_commit
from app.core.logging import get_logger
from app.models.document import Document, DocumentStatus, DocumentVersion
from app.models.job import Job, JobStatus
from app.models.organization import Collection, CollectionKind
from app.models.user import User
from app.services import organization as org
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.storage import FileStorage, get_storage
from app.workers.dispatcher import get_dispatcher

log = get_logger(__name__)

COLLECTION_NAME = "Sample papers"

# Directory holding genuine open-access research paper PDFs.
PAPERS_DIR = Path(__file__).parent / "papers"


@dataclass(frozen=True, slots=True)
class RealPaperAsset:
    filename: str
    title: str
    arxiv_id: str
    year: int
    asset_file: str


# The 3 genuine research papers for the public demo
RESEARCH_PAPERS: dict[str, RealPaperAsset] = {
    "attention-is-all-you-need.pdf": RealPaperAsset(
        filename="attention-is-all-you-need.pdf",
        title="Attention Is All You Need",
        arxiv_id="1706.03762",
        year=2017,
        asset_file="attention-is-all-you-need.pdf",
    ),
    "retrieval-augmented-generation.pdf": RealPaperAsset(
        filename="retrieval-augmented-generation.pdf",
        title="Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
        arxiv_id="2005.11401",
        year=2020,
        asset_file="retrieval-augmented-generation.pdf",
    ),
    "lora-low-rank-adaptation.pdf": RealPaperAsset(
        filename="lora-low-rank-adaptation.pdf",
        title="LoRA: Low-Rank Adaptation of Large Language Models",
        arxiv_id="2106.09685",
        year=2021,
        asset_file="lora-low-rank-adaptation.pdf",
    ),
}

# Legacy synthetic demo filenames that need reconciliation
LEGACY_SYNTHETIC_FILENAMES = {
    "sample-hybrid-retrieval.pdf",
    "sample-low-rank-adapters.pdf",
    "sample-rag-adapters.pdf",
}


def _get_paper_bytes(asset: RealPaperAsset) -> bytes:
    """Read the real paper PDF bytes from the packaged assets directory."""
    asset_path = PAPERS_DIR / asset.asset_file
    if asset_path.exists():
        return asset_path.read_bytes()
    raise FileNotFoundError(
        f"Real research paper asset not found at {asset_path}. "
        "Ensure papers are downloaded to backend/app/demo/papers/"
    )


async def _reconcile_legacy_synthetic_records(
    session: AsyncSession,
    demo_user_id: uuid.UUID,
) -> int:
    """Cleanly reconcile legacy synthetic demo records for the demo user only.

    Does NOT touch any other user's documents or data.
    """
    legacy_docs = (
        await session.execute(
            select(Document).where(
                Document.user_id == demo_user_id,
                Document.original_filename.in_(LEGACY_SYNTHETIC_FILENAMES),
            )
        )
    ).scalars().all()

    if not legacy_docs:
        return 0

    legacy_doc_ids = [d.id for d in legacy_docs]

    # Clean up jobs referencing these legacy synthetic docs
    await session.execute(
        delete(Job).where(
            Job.user_id == demo_user_id,
            Job.subject_id.in_(legacy_doc_ids),
        )
    )

    # Delete the legacy demo documents (cascades to versions, sections, elements, etc.)
    for doc in legacy_docs:
        doc.current_version_id = None
        await session.flush()
        await session.delete(doc)

    await session.commit()
    log.info("legacy_synthetic_demo_records_reconciled", count=len(legacy_docs))
    return len(legacy_docs)


async def restore_version_file(
    session: AsyncSession,
    settings: Settings,
    storage: FileStorage,
    version: DocumentVersion,
    document: Document | None = None,
) -> bool:
    """Idempotent, best-effort: restore `version`'s original file from the packaged
    demo asset if it is missing on disk and belongs to one of the 3 canonical demo
    papers. A no-op (returns False) for every other document, including other
    users' uploads, which have no packaged backup and so are correctly left alone.

    Safe to call on every request that touches a demo asset, not just at startup:
    Render's ephemeral disk can lose files mid-session (e.g. a redeploy or a
    forced restart while the app is serving traffic), not only between restarts,
    so self-healing only at process startup leaves a window where every page/
    figure/thumbnail request 500s until the next boot. This closes that window.
    """
    path = storage.path(version.storage_key)
    if path.exists():
        return False
    if document is None:
        document = await session.get(Document, version.document_id)
    if document is None or document.user_id != settings.demo_user_id:
        return False
    asset = RESEARCH_PAPERS.get(document.original_filename)
    if asset is None:
        return False
    data = _get_paper_bytes(asset)
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = Path(tmp) / document.original_filename
        pdf_path.write_bytes(data)
        storage.save(pdf_path, version.storage_key)
    log.info(
        "demo_real_paper_file_restored",
        filename=document.original_filename,
        document_id=str(document.id),
        storage_key=version.storage_key,
    )
    return True


async def _restore_missing_files(
    session: AsyncSession,
    settings: Settings,
    demo_user_id: uuid.UUID,
) -> dict[str, Any]:
    """Regenerate/restore demo PDFs missing from the local (ephemeral) filesystem.

    For each existing demo document whose storage file is absent, this:
    1. Restores the genuine PDF from the packaged assets.
    2. Copies it into the storage directory under the existing storage_key.
    3. If the document status is FAILED, resets it to QUEUED and re-enqueues
       the processing job so the pipeline runs again.

    Returns a summary dict with counts of files restored and jobs re-enqueued.
    """
    storage = get_storage(settings)
    restored = 0
    reenqueued = 0

    docs = (
        await session.execute(
            select(Document)
            .where(
                Document.user_id == demo_user_id,
                Document.original_filename.in_(RESEARCH_PAPERS),
            )
            .options(selectinload(Document.current_version))
        )
    ).scalars().all()

    for doc in docs:
        version: DocumentVersion | None = doc.current_version
        if version is None and doc.current_version_id is not None:
            version = await session.get(DocumentVersion, doc.current_version_id)
        if version is None:
            continue

        if await restore_version_file(session, settings, storage, version, document=doc):
            restored += 1

        # Re-enqueue failed documents for processing.
        if doc.status == DocumentStatus.FAILED:
            dispatcher = get_dispatcher(settings)
            job_service = JobService(session, dispatcher)
            doc.status = DocumentStatus.QUEUED
            doc.error_message = None
            job = await job_service.enqueue(
                doc.user_id,
                "document.process",
                payload={"version_id": str(version.id)},
                subject_type="document",
                subject_id=doc.id,
            )
            doc.processing_job_id = job.id
            reenqueued += 1
            log.info(
                "demo_job_reenqueued",
                document_id=str(doc.id),
                job_id=str(job.id),
            )

    if restored or reenqueued:
        await session.commit()
        run_after_commit(session)
        log.info(
            "demo_files_restored",
            restored=restored,
            reenqueued=reenqueued,
        )

    return {"restored": restored, "reenqueued": reenqueued}


async def ensure_shared_sample_library(
    settings: Settings, session_factory: async_sessionmaker[AsyncSession]
) -> dict[str, Any]:
    """Idempotently bootstrap the shared sample library under settings.demo_user_id."""
    demo_user_id = settings.demo_user_id

    async with session_factory() as session:
        # 1. Ensure system demo user exists
        demo_user = await session.get(User, demo_user_id)
        if demo_user is None:
            demo_user = User(
                id=demo_user_id,
                email="demo.system@research-intelligence.local",
                password_hash="!disabled-demo-system-account",
                full_name="Research Intelligence Demo",
                is_active=True,
            )
            session.add(demo_user)
            await session.commit()
            log.info("demo_system_user_created", user_id=str(demo_user_id))

        # 2. Reconcile any legacy synthetic papers
        await _reconcile_legacy_synthetic_records(session, demo_user_id)

        # 3. Check which genuine research papers are already present
        existing_filenames = set(
            (
                await session.execute(
                    select(Document.original_filename).where(
                        Document.user_id == demo_user_id,
                        Document.original_filename.in_(RESEARCH_PAPERS),
                    )
                )
            ).scalars()
        )

        missing = {fn: asset for fn, asset in RESEARCH_PAPERS.items() if fn not in existing_filenames}
        if not missing:
            # All documents exist in the DB. Restore any files lost to ephemeral
            # filesystem restarts and re-enqueue failed processing jobs.
            recovery = await _restore_missing_files(session, settings, demo_user_id)
            log.info(
                "shared_sample_library_already_populated",
                count=len(existing_filenames),
                **recovery,
            )
            return {"status": "ready", "count": len(existing_filenames), **recovery}

        # 4. Ingest missing genuine research papers
        storage = get_storage(settings)
        job_service = JobService(session, get_dispatcher(settings))
        doc_service = DocumentService(session, settings, storage, job_service)
        added_docs = []
        for filename, asset in missing.items():
            data = _get_paper_bytes(asset)
            upload = UploadFile(file=io.BytesIO(data), filename=filename)
            doc = await doc_service.upload(demo_user_id, upload)
            doc.title = asset.title
            added_docs.append(doc)
            log.info("shared_real_paper_uploaded", filename=filename, document_id=str(doc.id))

        # 5. Put all sample papers in the shared Collection
        collection = await session.scalar(
            select(Collection).where(
                Collection.user_id == demo_user_id, Collection.name == COLLECTION_NAME
            )
        )
        if collection is None:
            collection = Collection(
                user_id=demo_user_id,
                name=COLLECTION_NAME,
                description="Genuine open-access research papers for public demonstration.",
                kind=CollectionKind.PROJECT,
            )
            session.add(collection)
            await session.flush()

        all_doc_ids = list(
            (
                await session.execute(
                    select(Document.id).where(
                        Document.user_id == demo_user_id,
                        Document.original_filename.in_(RESEARCH_PAPERS),
                    )
                )
            ).scalars()
        )
        await org.add_to_collection(session, demo_user_id, collection, all_doc_ids)
        await session.commit()
        run_after_commit(session)

        log.info(
            "shared_sample_library_bootstrapped",
            added=len(added_docs),
            total=len(all_doc_ids),
        )
        return {"status": "bootstrapped", "added": len(added_docs), "total": len(all_doc_ids)}


