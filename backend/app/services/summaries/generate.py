"""Generating a summary: map over section groups, reduce to the takeaway, verify everything.

    for each section group (overview, method, experiments, outlook):
        FieldExtractor.run_group: passages → one model call → parse → cite → check
        → save (the UI shows sections as they arrive)
    takeaway ← model call over the drafted fields (cites the same passages) → check it

A field the passages don't answer is "Not reported." — said by the model, or set
without calling it when no passage exists for that part of the paper.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.document import Document, DocumentVersion
from app.models.summary import PaperSummary, SummaryStatus
from app.services.llm import GenerationParams, get_llm, provider_name, resolve_model
from app.services.rag.pipeline import get_verifier
from app.services.summaries.engine import (
    FieldExtractor,
    first_line,
    load_paper,
    overall_support,
)
from app.services.summaries.prompt import has_label, parse_fields, takeaway_messages
from app.services.summaries.spec import (
    FIELD_ORDER,
    FIELDS,
    GROUPS,
    NOT_REPORTED,
    PROMPT_VERSION,
    TAKEAWAY,
)

log = get_logger(__name__)
Report = Callable[[str, float, str | None], Awaitable[None]]
FIELD_BY_KEY = {f.key: f for f in FIELDS}


class SummaryGone(Exception):
    """The summary (or its paper) was deleted while it was being written."""


class SummaryFailedError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


async def generate_summary(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    summary_id: uuid.UUID,
    report: Report,
) -> dict[str, Any]:
    started = time.perf_counter()
    async with session_factory() as session:
        summary = await session.get(PaperSummary, summary_id)
        if summary is None:
            raise SummaryGone
        document = await session.get(Document, summary.document_id)
        version = await session.get(DocumentVersion, summary.version_id)
        if document is None or version is None:
            raise SummaryGone
        paper, chunks = await load_paper(session, document, version.id)
        chunking = version.chunking_strategy
        summary.status = SummaryStatus.RUNNING
        summary.sections, summary.sources, summary.support = [], [], None
        summary.error_message = None
        await session.commit()

    if not chunks:
        raise SummaryFailedError(
            "This paper has no indexed passages to summarize yet.",
            hint="Wait for indexing to finish, or re-run indexing from the paper's Overview.",
        )

    verifier = get_verifier(settings)
    extractor = FieldExtractor(
        paper,
        chunks,
        get_llm(settings),
        verifier,
        GenerationParams(settings.summary_max_tokens, settings.llm_temperature),
        settings.summary_context_tokens,
        settings.summary_max_passages,
    )
    config: dict[str, Any] = {
        "llm_provider": provider_name(settings),
        "llm_model": resolve_model(settings),
        "prompt_version": PROMPT_VERSION,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.summary_max_tokens,
        "context_tokens": settings.summary_context_tokens,
        "max_passages": settings.summary_max_passages,
        "chunking_strategy": chunking,
        "verifier": verifier.name if verifier else None,
    }
    steps = len(GROUPS) + 1

    async def save(**extra: Any) -> None:
        async with session_factory() as session:
            row = await session.get(PaperSummary, summary_id)
            if row is None:
                raise SummaryGone
            row.sections = sorted(extractor.sections, key=lambda s: FIELD_ORDER[s["key"]])
            row.sources = list(extractor.sources)
            row.trace = {"groups": list(extractor.trace)}
            row.generation_config = config | {"llm_model": extractor.model or config["llm_model"]}
            row.input_tokens = extractor.tokens["input"]
            row.output_tokens = extractor.tokens["output"]
            for name, value in extra.items():
                setattr(row, name, value)
            await session.commit()

    # --- map: one call per section group ------------------------------------------------------
    for step, group in enumerate(GROUPS):
        await report("summarizing", 0.03 + 0.95 * step / steps, group.detail)
        await extractor.run_group(group)
        await save()

    # --- reduce: the one-line takeaway ------------------------------------------------------
    await report("summarizing", 0.03 + 0.95 * len(GROUPS) / steps, "Writing the takeaway")
    entry: dict[str, Any] = {"group": "takeaway", "fields": [TAKEAWAY.key]}
    text = NOT_REPORTED
    drafted = [(FIELD_BY_KEY[key], value) for key, value in extractor.drafted]
    if drafted:
        reply = await extractor.generate(
            takeaway_messages(paper.title, paper.year, drafted, TAKEAWAY), entry
        )
        text = parse_fields(reply, [TAKEAWAY])[TAKEAWAY.key]
        if not has_label(reply, TAKEAWAY):
            text = first_line(reply) or NOT_REPORTED
    else:
        entry["note"] = "Nothing was reported in the other fields; the model wasn't called."
    await extractor.check(TAKEAWAY, text, {s["number"]: s["quote"] for s in extractor.sources})
    extractor.trace.append(entry)

    support = overall_support(
        extractor.claims, extractor.sections, verifier.name if verifier else "none"
    )
    extractor.finish_sources()
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    await save(status=SummaryStatus.READY, support=support, latency_ms=latency_ms)

    # The new summary replaces older ones for this paper (kept until now so the paper
    # always had one to show while this was generated).
    async with session_factory() as session:
        await session.execute(
            delete(PaperSummary).where(
                PaperSummary.document_id == paper.id, PaperSummary.id != summary_id
            )
        )
        await session.commit()
    metrics.inc("summaries_total", status="ready")
    metrics.observe("summary_latency_ms", latency_ms)
    log.info(
        "summary_generated",
        document_id=str(paper.id),
        sources=len(extractor.sources),
        support=support["status"],
        latency_ms=latency_ms,
    )
    return {
        "summary_id": str(summary_id),
        "support": support["status"],
        "sources": len(extractor.sources),
        "not_reported": support["not_reported"],
        "tokens": extractor.tokens,
        "latency_ms": latency_ms,
    }
