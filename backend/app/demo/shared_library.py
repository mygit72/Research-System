"""Shared sample research library management for the public demo.

Ensures that the 3 synthetic demonstration papers are pre-indexed under the
shared DEMO_USER_ID, so demo visitors immediately have access to a populated
research library without duplicating data for every user or consuming upload quota.
"""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.demo import sample_papers as sp
from app.models.document import Document, DocumentStatus
from app.models.organization import Collection, CollectionKind
from app.models.user import User
from app.services import organization as org
from app.services.documents import DocumentService

log = get_logger(__name__)

COLLECTION_NAME = "Sample papers"
SAMPLE_FILES = {
    "sample-hybrid-retrieval.pdf": sp.RETRIEVAL_PAPER,
    "sample-low-rank-adapters.pdf": sp.LORA_PAPER,
    "sample-rag-adapters.pdf": sp.RAG_ADAPTER_PAPER,
}


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
                hashed_password="!disabled-demo-system-account",
                full_name="Research Intelligence Demo",
                is_active=True,
            )
            session.add(demo_user)
            await session.commit()
            log.info("demo_system_user_created", user_id=str(demo_user_id))

        # 2. Check which sample papers are already present
        existing_filenames = set(
            (
                await session.execute(
                    select(Document.original_filename).where(
                        Document.user_id == demo_user_id,
                        Document.original_filename.in_(SAMPLE_FILES),
                    )
                )
            ).scalars()
        )

        missing = {fn: paper for fn, paper in SAMPLE_FILES.items() if fn not in existing_filenames}
        if not missing:
            log.info("shared_sample_library_already_populated", count=len(existing_filenames))
            return {"status": "ready", "count": len(existing_filenames)}

        # 3. Ingest missing sample papers
        doc_service = DocumentService(session, settings)
        added_docs = []
        with tempfile.TemporaryDirectory() as tmp:
            for filename, paper in missing.items():
                pdf_path = Path(tmp) / filename
                data = sp.write_sample_pdf(paper, pdf_path, demo=True).read_bytes()
                upload = UploadFile(file=io.BytesIO(data), filename=filename)
                doc = await doc_service.upload(demo_user_id, upload)
                added_docs.append(doc)
                log.info("shared_sample_paper_uploaded", filename=filename, document_id=str(doc.id))

        # 4. Put all sample papers in the shared Collection
        collection = await session.scalar(
            select(Collection).where(
                Collection.user_id == demo_user_id, Collection.name == COLLECTION_NAME
            )
        )
        if collection is None:
            collection = Collection(
                user_id=demo_user_id,
                name=COLLECTION_NAME,
                description="Synthetic research papers written for demonstration.",
                kind=CollectionKind.PROJECT,
            )
            session.add(collection)
            await session.flush()

        all_doc_ids = list(
            (
                await session.execute(
                    select(Document.id).where(
                        Document.user_id == demo_user_id,
                        Document.original_filename.in_(SAMPLE_FILES),
                    )
                )
            ).scalars()
        )
        await org.add_to_collection(session, demo_user_id, collection, all_doc_ids)
        await session.commit()

        log.info(
            "shared_sample_library_bootstrapped",
            added=len(added_docs),
            total=len(all_doc_ids),
        )
        return {"status": "bootstrapped", "added": len(added_docs), "total": len(all_doc_ids)}

