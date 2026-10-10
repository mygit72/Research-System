"""Demo mode: load the built-in sample papers into the signed-in user's library.

The three sample papers are original, synthetic content written for this project (no
copyrighted papers); their demo copies say so in every page header. They go through the
normal upload pipeline (validation, parsing, indexing), into a "Sample papers" collection,
so everything a new user tries — search, chat, summaries, comparisons — has data at once.
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, DocumentServiceDep
from app.demo import sample_papers as sp
from app.models.document import Document
from app.models.organization import Collection, CollectionKind
from app.services import organization as org

router = APIRouter(prefix="/demo", tags=["demo"])

COLLECTION = "Sample papers"
FILES = {
    "sample-hybrid-retrieval.pdf": sp.RETRIEVAL_PAPER,
    "sample-low-rank-adapters.pdf": sp.LORA_PAPER,
    "sample-rag-adapters.pdf": sp.RAG_ADAPTER_PAPER,
}


@router.post(
    "/sample-papers",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Add the three synthetic sample papers to your library (idempotent)",
)
async def add_sample_papers(
    user: CurrentUser, db: DbSession, documents: DocumentServiceDep
) -> dict[str, Any]:
    present = set(
        (
            await db.execute(
                select(Document.original_filename).where(
                    Document.user_id == user.id, Document.original_filename.in_(FILES)
                )
            )
        ).scalars()
    )
    added = []
    with tempfile.TemporaryDirectory() as tmp:
        for filename, paper in FILES.items():
            if filename in present:
                continue
            data = sp.write_sample_pdf(paper, Path(tmp) / filename, demo=True).read_bytes()
            upload = UploadFile(file=io.BytesIO(data), filename=filename)
            added.append(await documents.upload(user.id, upload))
    collection = await db.scalar(
        select(Collection).where(Collection.user_id == user.id, Collection.name == COLLECTION)
    )
    if collection is None:
        collection = Collection(
            user_id=user.id,
            name=COLLECTION,
            description="Synthetic papers written for demonstrating the platform.",
            kind=CollectionKind.PROJECT,
        )
        db.add(collection)
        await db.flush()
    ids = list(
        (
            await db.execute(
                select(Document.id).where(
                    Document.user_id == user.id, Document.original_filename.in_(FILES)
                )
            )
        ).scalars()
    )
    await org.add_to_collection(db, user.id, collection, ids)
    return {
        "added": len(added),
        "document_ids": [str(d) for d in ids],
        "collection_id": str(collection.id),
    }
