"""Generating a comparison: per-paper extraction (cached) → table → overview → checks.

    for each paper (column order):
        cached extraction for (version, kind, model, prompt version)?  → reuse it
        else FieldExtractor over the kind's section groups → cache it
        → the table so far is saved (columns fill in as papers are read)
    renumber every paper's passages into one source list ([1]… across papers)
    overview ← one model call over the finished table, checked against the passages it cites

Rows also get an `agreement` (similar / different / partial / none) computed from the
cells' words — a cue for "highlight differences", not a judgement by the model.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from itertools import combinations
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.comparison import Comparison, ComparisonStatus, PaperExtraction
from app.models.document import Document, DocumentVersion
from app.services.comparisons.prompt import letter, overview_messages
from app.services.comparisons.spec import (
    GROUPS,
    OVERVIEW,
    OVERVIEW_PROMPT_VERSION,
    PROMPT_VERSION,
    ROWS,
    ComparisonKind,
)
from app.services.llm import GenerationParams, get_llm, provider_name, resolve_model
from app.services.rag.pipeline import get_verifier
from app.services.rag.verify import ClaimResult
from app.services.retrieval.text import analyze
from app.services.summaries.engine import (
    RAW_REPLY_LIMIT,
    FieldExtractor,
    _claim_dict,
    build_section,
    complete,
    first_line,
    load_paper,
    overall_support,
)
from app.services.summaries.prompt import has_label, parse_fields
from app.services.summaries.spec import NOT_REPORTED

log = get_logger(__name__)
Report = Callable[[str, float, str | None], Awaitable[None]]
_CITATION = re.compile(r"\[(\d+)\]")
SIMILAR_JACCARD = 0.5


class ComparisonGone(Exception):
    """The comparison was deleted while it was being written."""


class ComparisonFailedError(Exception):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


def extraction_key(settings: Settings, version_id: uuid.UUID, kind: str) -> str:
    model = resolve_model(settings)
    return f"{version_id}:{kind}:{provider_name(settings)}:{model}:{PROMPT_VERSION}"


def agreement(cells: list[dict[str, Any]]) -> str:
    """similar / different between the reported cells; partial if some papers don't say."""
    reported = [c for c in cells if c["status"] != "not_reported"]
    if not reported:
        return "none"
    if len(reported) < len(cells):
        return "partial"
    terms = [set(analyze(_CITATION.sub("", c["text"]))) for c in reported]
    for first, second in combinations(terms, 2):
        union = first | second
        if not union or len(first & second) / len(union) < SIMILAR_JACCARD:
            return "different"
    return "similar"


def _shift(cell: dict[str, Any], offset: int) -> dict[str, Any]:
    """A paper's cell with its passage numbers moved into the comparison's numbering."""

    def number(value: int | None) -> int | None:
        return None if value is None else value + offset

    return cell | {
        "text": _CITATION.sub(lambda m: f"[{int(m[1]) + offset}]", cell["text"]),
        "citations": [n + offset for n in cell["citations"]],
        "invalid_citations": [],
        "claims": [
            claim
            | {
                "citations": [n + offset for n in claim["citations"]],
                "best_passage": number(claim["best_passage"]),
                "found_in": number(claim.get("found_in")),
            }
            for claim in cell["claims"]
        ],
    }


def short_title(title: str, limit: int = 48) -> str:
    head = title.split(":")[0].strip() or title
    return head if len(head) <= limit else head[: limit - 1].rstrip() + "…"


async def generate_comparison(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    comparison_id: uuid.UUID,
    report: Report,
) -> dict[str, Any]:
    started = time.perf_counter()
    async with session_factory() as session:
        comparison = await session.get(Comparison, comparison_id)
        if comparison is None:
            raise ComparisonGone
        kind = ComparisonKind(comparison.kind)
        user_id = comparison.user_id
        document_ids = [uuid.UUID(d) for d in comparison.document_ids]
        comparison.status = ComparisonStatus.RUNNING
        comparison.rows, comparison.sources, comparison.overview = [], [], None
        comparison.error_message = None
        await session.commit()

    llm = get_llm(settings)
    verifier = get_verifier(settings)
    params = GenerationParams(settings.summary_max_tokens, settings.llm_temperature)
    groups = GROUPS[kind]
    config: dict[str, Any] = {
        "llm_provider": provider_name(settings),
        "llm_model": resolve_model(settings),
        "prompt_version": PROMPT_VERSION,
        "overview_prompt_version": OVERVIEW_PROMPT_VERSION,
        "kind": kind.value,
        "context_tokens": settings.summary_context_tokens,
        "max_passages": settings.summary_max_passages,
        "verifier": verifier.name if verifier else None,
    }
    columns: list[dict[str, Any]] = []
    papers: list[dict[str, Any]] = []  # per column: sections by key, sources, claims
    tokens = {"input": 0, "output": 0}
    trace: dict[str, Any] = {"papers": []}
    total_calls = len(document_ids) * len(groups) + 1
    calls_done = 0

    async def save(**extra: Any) -> None:
        async with session_factory() as session:
            row = await session.get(Comparison, comparison_id)
            if row is None:
                raise ComparisonGone
            row.columns = list(columns)
            row.rows, row.sources = build_table(kind, columns, papers)
            row.trace = dict(trace)
            row.generation_config = dict(config)
            row.input_tokens, row.output_tokens = tokens["input"], tokens["output"]
            for name, value in extra.items():
                setattr(row, name, value)
            await session.commit()

    # --- map: each paper's fields (cached per paper version) -----------------------------
    for index, document_id in enumerate(document_ids):
        async with session_factory() as session:
            document = await session.get(Document, document_id)
            if document is None or document.user_id != user_id:
                raise ComparisonFailedError(
                    "One of the papers was deleted. Start a new comparison."
                )
            version = (
                await session.get(DocumentVersion, document.current_version_id)
                if document.current_version_id
                else None
            )
            if version is None:
                raise ComparisonFailedError(f"“{document.title}” hasn't finished processing.")
            key = extraction_key(settings, version.id, kind.value)
            cached = await session.scalar(
                select(PaperExtraction)
                .where(PaperExtraction.version_id == version.id)
                .where(PaperExtraction.config_key == key)
                .order_by(PaperExtraction.created_at.desc())
                .limit(1)
            )
            if cached is None:
                paper, chunks = await load_paper(session, document, version.id)
            title, year, authors = document.title, document.year, document.authors_display
        column = {
            "document_id": str(document_id),
            "version_id": str(version.id),
            "letter": letter(index),
            "title": title,
            "year": year,
            "authors_display": authors,
        }
        if cached is not None:
            column["extraction_id"] = str(cached.id)
            papers.append(
                {"sections": cached.sections, "sources": cached.sources, "claims": cached.claims}
            )
            trace["papers"].append({"document_id": str(document_id), "cached": True})
            calls_done += len(groups)
        else:
            if not chunks:
                raise ComparisonFailedError(
                    f"“{title}” has no indexed passages yet.",
                    hint="Wait for indexing to finish, or re-run indexing from its Overview.",
                )
            paper_started = time.perf_counter()
            extractor = FieldExtractor(
                paper, chunks, llm, verifier, params,
                settings.summary_context_tokens, settings.summary_max_passages,
            )  # fmt: skip
            for group in groups:
                detail = (
                    f"Reading {group.detail} of “{short_title(title)}” "
                    f"(paper {index + 1} of {len(document_ids)})"
                )
                await report("comparing", 0.03 + 0.95 * calls_done / total_calls, detail)
                await extractor.run_group(group)
                calls_done += 1
            extractor.finish_sources()
            tokens["input"] += extractor.tokens["input"]
            tokens["output"] += extractor.tokens["output"]
            if extractor.model:
                config["llm_model"] = extractor.model
            claims = [_claim_dict(c) for c in extractor.claims]
            async with session_factory() as session:
                extraction = PaperExtraction(
                    user_id=user_id,
                    document_id=document_id,
                    version_id=version.id,
                    kind=kind.value,
                    config_key=key,
                    sections=extractor.sections,
                    sources=extractor.sources,
                    claims=claims,
                    trace=extractor.trace,
                    llm_model=extractor.model,
                    input_tokens=extractor.tokens["input"],
                    output_tokens=extractor.tokens["output"],
                    latency_ms=round((time.perf_counter() - paper_started) * 1000, 1),
                )
                session.add(extraction)
                await session.commit()
                column["extraction_id"] = str(extraction.id)
            papers.append(
                {"sections": extractor.sections, "sources": extractor.sources, "claims": claims}
            )
            trace["papers"].append(
                {"document_id": str(document_id), "cached": False, "groups": extractor.trace}
            )
        columns.append(column)
        await save()

    # --- reduce: the overview above the table --------------------------------------------
    await report("comparing", 0.03 + 0.95 * calls_done / total_calls, "Writing the overview")
    rows, sources = build_table(kind, columns, papers)
    table = [(r["title"], [c["text"] for c in r["cells"]]) for r in rows]
    entry: dict[str, Any] = {"group": "overview"}
    overview_text = NOT_REPORTED
    if any(c["status"] != "not_reported" for r in rows for c in r["cells"]):
        mark = time.perf_counter()
        result = await complete(
            llm,
            overview_messages([(c["title"], c["year"]) for c in columns], table, OVERVIEW),
            params,
        )
        tokens["input"] += result.input_tokens
        tokens["output"] += result.output_tokens
        entry |= {
            "reply": result.text[:RAW_REPLY_LIMIT],
            "latency_ms": round((time.perf_counter() - mark) * 1000, 1),
        }
        overview_text = parse_fields(result.text, [OVERVIEW])[OVERVIEW.key]
        if not has_label(result.text, OVERVIEW):
            overview_text = first_line(result.text) or NOT_REPORTED
    else:
        entry["note"] = "No paper reports any of the rows; the model wasn't called."
    trace["overview"] = entry
    # Each passage is checked with its own paper's title as context.
    passages = {s["number"]: s["quote"] for s in sources}
    titles = {s["number"]: s["document"]["title"] for s in sources}
    overview, overview_claims = await asyncio.to_thread(
        build_section, OVERVIEW, overview_text, passages, verifier, titles
    )

    all_claims = [ClaimResult(**c) for p in papers for c in p["claims"]] + overview_claims
    cells = [cell | {"title": r["title"]} for r in rows for cell in r["cells"]]
    support = overall_support(all_claims, cells, verifier.name if verifier else "none")
    support["not_reported"] = sorted(
        {
            f"{r['title']} ({c['letter']})"
            for r in rows
            for c in r["cells"]
            if c["status"] == "not_reported"
        }
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    await save(
        status=ComparisonStatus.READY, overview=overview, support=support, latency_ms=latency_ms
    )
    metrics.inc("comparisons_total", kind=kind.value)
    metrics.observe("comparison_latency_ms", latency_ms)
    log.info("comparison_generated", papers=len(columns), kind=kind.value, latency_ms=latency_ms)
    return {
        "comparison_id": str(comparison_id),
        "papers": len(columns),
        "cached_papers": sum(1 for p in trace["papers"] if p["cached"]),
        "support": support["status"],
        "tokens": tokens,
        "latency_ms": latency_ms,
    }


def build_table(
    kind: ComparisonKind, columns: list[dict[str, Any]], papers: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rows (one cell per paper so far) and one source list numbered across the papers."""
    sources: list[dict[str, Any]] = []
    shifted: list[dict[str, dict[str, Any]]] = []
    for column, paper in zip(columns, papers, strict=True):
        offset = len(sources)
        sources += [
            s | {"number": s["number"] + offset, "letter": column["letter"]}
            for s in paper["sources"]
        ]
        shifted.append({s["key"]: _shift(s, offset) for s in paper["sections"]})
    rows = []
    for field in ROWS[kind]:
        cells = []
        for column, sections in zip(columns, shifted, strict=True):
            section = sections.get(field.key)
            cell = section or {
                "key": field.key, "title": field.title, "text": NOT_REPORTED, "citations": [],
                "invalid_citations": [], "status": "not_reported", "label": "Not reported",
                "explanation": "", "claims": [],
            }  # fmt: skip
            cells.append(cell | {"document_id": column["document_id"], "letter": column["letter"]})
        rows.append(
            {"key": field.key, "title": field.title, "agreement": agreement(cells), "cells": cells}
        )
    return rows, sources
