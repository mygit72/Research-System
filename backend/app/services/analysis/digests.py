"""Paper digests: each paper's verified statements, from its structured summary.

Every analysis in this package (themes, gaps, disagreements) works from the same unit: a
statement the summary wrote about a paper, the passages it cites, and whether the NLI check
supported it. Only supported / partly supported statements are used, so a review never
builds on a sentence its own check rejected.

Summaries are reused when current (same version, model and prompt version); missing or
outdated ones are written here, one paper after another (a CPU machine runs one model).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.document import Chunk, Document, DocumentStatus
from app.models.summary import PaperSummary, SummaryStatus
from app.services.analysis.text import shorten
from app.services.summaries.generate import generate_summary
from app.services.summaries.service import config_key, last_ready_summary, staleness

Report = Callable[[str, float, str | None], Awaitable[None]]
USABLE = ("supported", "partial")


@dataclass
class Statement:
    field: str  # problem | method | dataset | results | limitations | future_work | …
    text: str
    status: str  # supported | partial
    sources: list[dict[str, Any]]  # the summary's passages this statement cites


@dataclass
class Digest:
    document_id: uuid.UUID
    title: str
    year: int | None
    authors: str
    summary_id: uuid.UUID
    statements: list[Statement] = field(default_factory=list)
    reused: bool = True  # False: the summary was written for this report

    def of(self, *fields: str) -> list[Statement]:
        return [s for s in self.statements if s.field in fields]


def digest_from_summary(document: Document, summary: PaperSummary, reused: bool) -> Digest:
    sources = {s["number"]: s for s in summary.sources or []}
    digest = Digest(
        document.id,
        document.title,
        document.year,
        document.authors_display,
        summary.id,
        reused=reused,
    )
    for section in summary.sections or []:
        for claim in section.get("claims", []):
            if claim.get("status") not in USABLE:
                continue
            numbers = list(claim.get("citations") or [])
            if not numbers and claim.get("found_in"):
                numbers = [claim["found_in"]]
            cited = [sources[n] for n in numbers if n in sources]
            if cited:
                digest.statements.append(
                    Statement(section["key"], claim["text"], claim["status"], cited)
                )
    return digest


async def ensure_digests(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    report: Report,
    start: float,
    end: float,
) -> tuple[list[Digest], list[dict[str, Any]]]:
    """Digests for these papers (in the given order) and the papers that had to be skipped."""
    digests: list[Digest] = []
    skipped: list[dict[str, Any]] = []
    for index, document_id in enumerate(document_ids):
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.user_id != user_id:
                continue
            if document.status != DocumentStatus.READY or document.current_version_id is None:
                skipped.append({"document_id": str(document_id), "reason": "not_ready"})
                continue
            has_passages = await session.scalar(
                select(Chunk.id).where(Chunk.version_id == document.current_version_id).limit(1)
            )
            if has_passages is None:
                skipped.append({"document_id": str(document_id), "reason": "not_indexed"})
                continue
            summary = await last_ready_summary(session, document_id)
            if summary is not None and staleness(summary, document, settings) is None:
                digests.append(digest_from_summary(document, summary, reused=True))
                continue
            new = PaperSummary(
                user_id=user_id,
                document_id=document_id,
                version_id=document.current_version_id,
                config_key=config_key(settings, document.current_version_id),
            )
            session.add(new)
            await session.commit()
            new_id, title = new.id, document.title

        span = (end - start) / max(len(document_ids), 1)
        base = start + span * index

        async def relay(
            _: str,
            fraction: float,
            detail: str | None,
            base: float = base,
            span: float = span,
            title: str = title,
        ) -> None:
            await report(
                "reading",
                base + span * fraction,
                f"Reading “{shorten(title, 60)}”: {detail or ''}".strip(),
            )

        await generate_summary(session_factory, settings, new_id, relay)
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            summary = await session.get(PaperSummary, new_id)
            if (
                document is not None
                and summary is not None
                and summary.status == SummaryStatus.READY
            ):
                digests.append(digest_from_summary(document, summary, reused=False))
    return digests, skipped


class SourceBook:
    """One numbering for every passage a report cites ([1], [2], … across papers)."""

    def __init__(self) -> None:
        self.items: list[dict[str, Any]] = []
        self._by_chunk: dict[str, int] = {}

    def add(self, source: dict[str, Any]) -> int:
        key = str(
            source.get("chunk_id") or f"{source['document']['id']}:{source.get('quote', '')[:80]}"
        )
        if key not in self._by_chunk:
            number = len(self.items) + 1
            self._by_chunk[key] = number
            self.items.append(
                {
                    "number": number,
                    "chunk_id": source.get("chunk_id"),
                    "document": source["document"],
                    "section_title": source.get("section_title", ""),
                    "page_start": source.get("page_start"),
                    "page_end": source.get("page_end"),
                    "char_start": source.get("char_start"),
                    "boxes": source.get("boxes", []),
                    "quote": source.get("quote", ""),
                }
            )
        return self._by_chunk[key]

    def text(self, number: int) -> str:
        return str(self.items[number - 1]["quote"])

    def title(self, number: int) -> str:
        return str(self.items[number - 1]["document"]["title"])

    def cite(self, statement: Statement) -> list[int]:
        return [self.add(s) for s in statement.sources]
