"""Personal data export: everything a user owns, as one .zip.

- `*.json`: every row the user owns, table by table, with all columns — except secrets
  (password hash, refresh-token hashes) and data derived from the papers that can be rebuilt
  by uploading them again (page text, sections, passages, embeddings, the knowledge graph).
- `files/`: the original uploads, every version, under their original names.
- `README.txt`: what is where.

Written to a spooled temporary file (memory, then disk past 32 MB) so a large library
doesn't have to fit in memory.
"""

from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from datetime import UTC, datetime
from typing import IO, Any

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Bookmark,
    ChatMessage,
    Collection,
    CollectionDocument,
    Comparison,
    Conversation,
    Document,
    DocumentMetadata,
    DocumentTag,
    DocumentVersion,
    EvalDataset,
    EvalItem,
    EvalRun,
    LLMUsage,
    Note,
    PaperSummary,
    ResearchProject,
    ResearchReport,
    Tag,
    User,
)
from app.models.audit import AuditLog
from app.models.chat import Citation
from app.models.model_choice import UserModelChoice
from app.services.storage import FileStorage

# Never exported: a password hash, session tokens, the encrypted API key a user saved.
SECRET_COLUMNS = {"password_hash", "token_hash", "api_key_encrypted"}

README = """Research Intelligence — your data export ({when})

account.json        your profile, preferences and model choice (never your API key)
activity.json       security activity: sign-ins, password changes, sessions, deletions
library.json        papers (with metadata and versions), collections, tags, notes, bookmarks
chat.json           conversations, messages and the passages each answer cited
analysis.json       paper summaries, comparisons, reviews and reports, research projects
evaluation.json     evaluation datasets, questions and runs
usage.json          language-model calls: tokens, cost, timing
files/              your original uploads (every version), as you uploaded them

Not included, because it is rebuilt from your papers when you upload them again: page text,
sections, passages, embeddings, the knowledge graph and topic maps.
"""


def _row(obj: Any) -> dict[str, Any]:
    return {
        column.key: getattr(obj, column.key)
        for column in inspect(obj).mapper.column_attrs
        if column.key not in SECRET_COLUMNS
    }


async def _all(session: AsyncSession, query: Any) -> list[dict[str, Any]]:
    rows: list[Any] = list((await session.execute(query)).scalars())
    return [_row(obj) for obj in rows]


def _json(data: Any) -> bytes:
    return json.dumps(data, indent=2, ensure_ascii=False, default=str).encode()


async def build_export(session: AsyncSession, storage: FileStorage, user: User) -> IO[bytes]:
    uid = user.id
    owned_papers = select(Document.id).where(Document.user_id == uid)
    documents = list(
        (await session.execute(select(Document).where(Document.user_id == uid))).scalars()
    )
    versions = list(
        (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.document_id.in_(owned_papers))
            )
        ).scalars()
    )
    owned_versions = select(DocumentVersion.id).where(DocumentVersion.document_id.in_(owned_papers))
    sections: dict[str, Any] = {
        "account.json": {
            **_row(user),
            "model_choice": await _all(
                session, select(UserModelChoice).where(UserModelChoice.user_id == uid)
            ),
        },
        "activity.json": await _all(
            session, select(AuditLog).where(AuditLog.user_id == uid).order_by(AuditLog.created_at)
        ),
        "library.json": {
            "papers": [_row(d) for d in documents],
            "versions": [_row(v) for v in versions],
            "metadata": await _all(
                session,
                select(DocumentMetadata).where(DocumentMetadata.version_id.in_(owned_versions)),
            ),
            "collections": await _all(session, select(Collection).where(Collection.user_id == uid)),
            "collection_papers": await _all(
                session,
                select(CollectionDocument)
                .join(Collection, Collection.id == CollectionDocument.collection_id)
                .where(Collection.user_id == uid),
            ),
            "tags": await _all(session, select(Tag).where(Tag.user_id == uid)),
            "paper_tags": await _all(
                session, select(DocumentTag).where(DocumentTag.document_id.in_(owned_papers))
            ),
            "notes": await _all(session, select(Note).where(Note.user_id == uid)),
            "bookmarks": await _all(session, select(Bookmark).where(Bookmark.user_id == uid)),
        },
        "chat.json": {
            "conversations": await _all(
                session, select(Conversation).where(Conversation.user_id == uid)
            ),
            "messages": await _all(session, select(ChatMessage).where(ChatMessage.user_id == uid)),
            "citations": await _all(
                session,
                select(Citation)
                .join(ChatMessage, ChatMessage.id == Citation.message_id)
                .where(ChatMessage.user_id == uid),
            ),
        },
        "analysis.json": {
            "summaries": await _all(
                session, select(PaperSummary).where(PaperSummary.user_id == uid)
            ),
            "comparisons": await _all(session, select(Comparison).where(Comparison.user_id == uid)),
            "reports": await _all(
                session, select(ResearchReport).where(ResearchReport.user_id == uid)
            ),
            "projects": await _all(
                session, select(ResearchProject).where(ResearchProject.user_id == uid)
            ),
        },
        "evaluation.json": {
            "datasets": await _all(session, select(EvalDataset).where(EvalDataset.user_id == uid)),
            "questions": await _all(
                session,
                select(EvalItem)
                .join(EvalDataset, EvalDataset.id == EvalItem.dataset_id)
                .where(EvalDataset.user_id == uid),
            ),
            "runs": await _all(session, select(EvalRun).where(EvalRun.user_id == uid)),
        },
        "usage.json": await _all(session, select(LLMUsage).where(LLMUsage.user_id == uid)),
    }

    out = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)  # noqa: SIM115 (returned)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("README.txt", README.format(when=datetime.now(UTC).isoformat()))
        for name, data in sections.items():
            archive.writestr(name, _json(data))
        for version in versions:
            source = storage.path(version.storage_key)
            if not source.exists():
                continue
            name = f"v{version.version_number}-{version.original_filename}"
            archive.write(source, f"files/{str(version.document_id)[:8]}/{name}")
    out.seek(0)
    return out


def export_filename(user_id: uuid.UUID) -> str:
    return f"research-intelligence-export-{datetime.now(UTC):%Y%m%d}-{str(user_id)[:8]}.zip"
