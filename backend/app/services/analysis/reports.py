"""Literature reviews, research-gap reports and disagreement reports.

A literature review, step by step (the stages the UI shows):

1. **Finding relevant papers** — the chosen papers or collection; or, from a topic, a hybrid
   search over the library aggregated to papers (reciprocal-rank sum of their passages).
2. **Reading** — each paper's digest (its verified summary statements; written if missing).
3. **Grouping research** — papers clustered by their embeddings (K-Means, k by silhouette),
   each group named by the language model (kept only if the name fits the group).
4. **Analyzing methodologies** — a comparison table and a chronology built from the
   knowledge layer (datasets, metrics, what each paper proposes) — no model involved.
5. **Identifying gaps and disagreements** — see `gaps.py` and `disagreements.py`.
6. **Writing** an overview and one paragraph per group from numbered passages, and
7. **verifying** every written sentence against the passages it cites.

Gap and disagreement reports run the same steps without the writing.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import ValidationError
from app.models.document import Document, DocumentStatus
from app.models.report import ReportKind, ReportStatus, ResearchReport
from app.services import organization as org
from app.services.analysis.digests import Digest, SourceBook, ensure_digests
from app.services.analysis.disagreements import describe, find_disagreements
from app.services.analysis.gaps import (
    STATED,
    SYNTHESIS,
    combination_gaps,
    directions_messages,
    disagreement_gaps,
    parse_directions,
    stated_gaps,
)
from app.services.analysis.text import shorten
from app.services.analysis.writing import PROMPT_VERSION, Writer, support_summary
from app.services.knowledge import clustering as algo
from app.services.knowledge.entities import ensure_entities
from app.services.knowledge.library import Library, load_library
from app.services.knowledge.topics import (
    clean_name,
    ctfidf_terms,
    fallback_name,
    grounded,
    library_vectors,
    naming_prompt,
)
from app.services.llm import GenerationParams, Message, get_llm, provider_name, resolve_model
from app.services.rag.pipeline import get_verifier
from app.services.retrieval.service import SearchFilters, SearchRequest, search
from app.services.retrieval.types import SearchMode

Report = Callable[[str, float, str | None], Awaitable[None]]
DEPTHS = {"brief": 6, "standard": 10, "detailed": 16}
THEME_FIELDS = ("contribution", "method", "results")
MIN_PAPERS = {ReportKind.REVIEW: 2, ReportKind.GAPS: 1, ReportKind.DISAGREEMENTS: 2}
SPARSE = {"bm25", "postgres_fts"}


class ReportGone(Exception):
    """The report was deleted while it was being generated."""


# --- choosing papers -----------------------------------------------------------------------------


async def choose_papers(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    topic: str,
    document_ids: list[uuid.UUID],
    collection_id: uuid.UUID | None,
    limit: int,
) -> tuple[list[uuid.UUID], dict[str, Any]]:
    """Papers for a report and how they were found (for the trace)."""
    if document_ids:
        docs = await org.owned_documents(session, user_id, document_ids)
        return [d.id for d in docs][:limit], {"how": "selected"}
    scope: list[uuid.UUID] | None = None
    if collection_id is not None:
        await org.get_collection(session, user_id, collection_id)
        scope = await org.collection_document_ids(session, collection_id)
        if not topic.strip():
            ready = (
                await session.execute(
                    select(Document.id).where(
                        Document.id.in_(scope), Document.status == DocumentStatus.READY
                    )
                )
            ).scalars()
            ready_ids = set(ready)
            return [d for d in scope if d in ready_ids][:limit], {"how": "collection"}
    if not topic.strip():
        raise ValidationError("Give a topic, choose papers, or choose a collection.")
    outcome = await search(
        session,
        settings,
        user_id,
        SearchRequest(
            topic,
            SearchMode.HYBRID,
            SearchFilters(document_ids=scope) if scope is not None else SearchFilters(),
            limit=80,
            rerank=False,
        ),
    )
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, int] = {}
    keyword: set[uuid.UUID] = set()
    for result in outcome.results:
        # Reciprocal-rank sum: a paper with several well-ranked passages is about the topic.
        scores[result.document.id] = scores.get(result.document.id, 0.0) + 1 / (10 + result.rank)
        hits[result.document.id] = hits.get(result.document.id, 0) + 1
        if SPARSE & set(result.matched_by):
            keyword.add(result.document.id)
    # Dense search always returns *something*, even for a topic no paper is about; a paper
    # qualifies only if its text also contains the topic's words (a keyword-retriever match).
    ranked = sorted((d for d in scores if d in keyword), key=lambda d: -scores[d])
    chosen = ranked[:limit]
    return chosen, {
        "how": "search",
        "rule": "papers with passages matching the topic's words, by reciprocal-rank sum",
        "query": topic,
        "candidates": [
            {"document_id": str(d), "score": round(scores[d], 4), "passages": hits[d]}
            for d in sorted(scores, key=lambda d: -scores[d])[:30]
        ],
    }


# --- grouping ------------------------------------------------------------------------------------


async def group_papers(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, digests: list[Digest]
) -> list[list[Digest]]:
    """Cluster the papers by their embeddings; small sets stay one group."""
    if len(digests) < 4:
        return [digests]
    library = await library_vectors(session, settings, user_id)
    index = {doc_id: i for i, doc_id in enumerate(library.document_ids)}
    with_vectors = [d for d in digests if d.document_id in index]
    if len(with_vectors) < 4:
        return [digests]
    vectors = np.vstack([library.vectors[index[d.document_id]] for d in with_vectors])
    auto = algo.auto_kmeans(vectors, k_min=2, k_max=min(4, len(with_vectors) // 2))
    groups: dict[int, list[Digest]] = {}
    for label, digest in zip(auto.result.labels.tolist(), with_vectors, strict=True):
        groups.setdefault(label, []).append(digest)
    leftovers = [d for d in digests if d.document_id not in index]
    ordered = sorted(groups.values(), key=lambda g: (-len(g), g[0].title))
    if leftovers:
        ordered[0].extend(leftovers)
    return ordered


async def name_groups(
    writer: Writer, groups: list[list[Digest]], abstracts: dict[uuid.UUID, str], topic: str
) -> list[dict[str, Any]]:
    texts = [[f"{d.title} {abstracts.get(d.document_id, '')}" for d in g] for g in groups]
    terms = ctfidf_terms(texts)
    clusters: list[dict[str, Any]] = [
        {
            "id": i,
            "document_ids": [str(d.document_id) for d in g],
            "terms": t,
            "entities": [],
        }
        for i, (g, t) in enumerate(zip(groups, terms, strict=True))
    ]
    titles = {str(d.document_id): d.title for g in groups for d in g}
    named = []
    for cluster in clusters:
        name, source = fallback_name(cluster["terms"], []), "terms"
        if len(groups) == 1 and topic.strip():
            name, source = shorten(topic, 80), "topic"  # one group: it *is* the topic
        elif len(groups) > 1:
            reply = await writer.generate(
                [Message("user", naming_prompt(cluster, titles))], f"name-{cluster['id']}"
            )
            candidate = clean_name(reply)
            if candidate and grounded(candidate, cluster, clusters, titles):
                name, source = candidate, "model"
        named.append({**cluster, "name": name, "name_source": source})
    return named


# --- deterministic sections ----------------------------------------------------------------------


def _entities_of(library: Library, document_id: uuid.UUID, kind: str) -> list[str]:
    return sorted(
        {
            library.entities[link.entity_id].name
            for link in library.links_of(document_id)
            if link.relation in ("proposes", "uses")
            and library.entities[link.entity_id].type == kind
        }
    )


def _proposed(library: Library, document_id: uuid.UUID) -> list[str]:
    return sorted(
        library.entities[link.entity_id].name
        for link in library.links_of(document_id)
        if link.relation == "proposes"
    )


def chronology_section(digests: list[Digest], library: Library) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for d in sorted(digests, key=lambda d: (d.year or 9999, d.title)):
        proposes = sorted(
            library.entities[link.entity_id].name
            for link in library.links_of(d.document_id)
            if link.relation == "proposes"
        )
        rows.append(
            {
                "year": d.year,
                "document": {"id": str(d.document_id), "title": d.title},
                "proposes": proposes,
            }
        )
    lines = [
        f"- **{r['year'] or 'No year'}** — {r['document']['title']}"
        + (f" (proposes {', '.join(r['proposes'])})" if r["proposes"] else "")
        for r in rows
    ]
    return {
        "key": "chronology",
        "title": "Chronology",
        "kind": "chronology",
        "text": "\n".join(lines),
        "data": {"rows": rows},
        "citations": [],
        "claims": [],
        "status": "derived",
        "label": "From the papers' metadata and extracted entities",
        "origin": "derived",
    }


def comparison_section(
    digests: list[Digest], groups: list[dict[str, Any]], library: Library, book: SourceBook
) -> dict[str, Any]:
    # A single group is named after the topic itself, which says nothing about a paper: show what
    # each paper proposes instead.
    topic_only = len(groups) == 1 and groups[0].get("name_source") == "topic"
    group_of = (
        {} if topic_only else {doc_id: g["name"] for g in groups for doc_id in g["document_ids"]}
    )
    rows = []
    for d in sorted(digests, key=lambda d: (d.year or 9999, d.title)):
        # The verified results statement; without one, what the paper contributes (labelled).
        result = next(iter(d.of("results") + d.of("contribution") + d.of("takeaway")), None)
        rows.append(
            {
                "document": {"id": str(d.document_id), "title": d.title, "year": d.year},
                "approach": group_of.get(str(d.document_id), "")
                or ", ".join(_proposed(library, d.document_id)),
                "datasets": _entities_of(library, d.document_id, "dataset")[:5],
                "metrics": _entities_of(library, d.document_id, "metric")[:4],
                "result": result.text if result else "Not reported.",
                "result_field": result.field if result else None,
                "citations": book.cite(result) if result else [],
            }
        )
    return {
        "key": "comparison",
        "title": "Comparison of approaches",
        "kind": "table",
        "text": "",
        "data": {"rows": rows},
        "citations": sorted({n for r in rows for n in r["citations"]}),
        "claims": [],
        "status": "derived",
        "label": "Results are the papers' verified summary statements",
        "origin": "derived",
    }


def disagreements_section(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": "disagreements",
        "title": "Potential disagreements",
        "kind": "disagreements",
        "text": "",
        "data": {"items": items},
        "citations": sorted(
            {n for i in items for n in [*i["claim_a"]["citations"], *i["claim_b"]["citations"]]}
        ),
        "claims": [],
        "status": "derived",
        "label": "Flagged by the entailment model; not a judgement of which paper is right",
        "origin": "derived",
    }


def gaps_section(gaps: list[dict[str, Any]], directions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "key": "gaps",
        "title": "Limitations and research gaps",
        "kind": "gaps",
        "text": "",
        "data": {"gaps": gaps, "directions": directions, "origins": [STATED, SYNTHESIS]},
        "citations": sorted({n for g in gaps for s in g["statements"] for n in s["citations"]}),
        "claims": [],
        "status": "derived",
        "label": f"“{STATED}” items are the papers' own words; “{SYNTHESIS}” items are not",
        "origin": "derived",
    }


# --- running -------------------------------------------------------------------------------------


async def generate_report(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    report_id: uuid.UUID,
    progress: Report,
) -> dict[str, Any]:
    started = time.perf_counter()
    async with session_factory() as session:
        report = await session.get(ResearchReport, report_id)
        if report is None:
            raise ReportGone
        report.status = ReportStatus.RUNNING
        report.error_message = None
        await session.commit()
        kind, user_id, topic = ReportKind(report.kind), report.user_id, report.query
        params = dict(report.params)

    if kind == ReportKind.DEEP_RESEARCH:
        from app.services.analysis.deep_research import run_deep_research

        return await run_deep_research(session_factory, settings, report_id, progress)

    limit = DEPTHS.get(params.get("depth", "standard"), DEPTHS["standard"])
    await progress("finding", 0.02, "Finding relevant papers")
    async with session_factory() as session:
        chosen, how = await choose_papers(
            session,
            settings,
            user_id,
            topic,
            [uuid.UUID(d) for d in params.get("document_ids", [])],
            uuid.UUID(params["collection_id"]) if params.get("collection_id") else None,
            limit,
        )
    if len(chosen) < MIN_PAPERS[kind]:
        raise ValidationError(
            f"Found {len(chosen)} relevant paper{'s' if len(chosen) != 1 else ''}; this needs at "
            f"least {MIN_PAPERS[kind]}.",
            hint="Choose papers or a collection, or upload more papers on this topic.",
        )

    digests, skipped = await ensure_digests(
        session_factory, settings, user_id, chosen, progress, 0.05, 0.6
    )
    if len(digests) < MIN_PAPERS[kind]:
        raise ValidationError(
            "Not enough of these papers could be read (they need to be processed and indexed).",
        )
    verifier = get_verifier(settings)
    book = SourceBook()
    writer = Writer(
        get_llm(settings),
        GenerationParams(settings.summary_max_tokens, settings.llm_temperature),
        verifier,
        book,
    )
    async with session_factory() as session:
        await ensure_entities(session, user_id)
        library = await load_library(session, user_id)
        abstracts = {
            p.id: p.abstract or ""
            for p in library.papers.values()
            if p.id in {d.document_id for d in digests}
        }

    sections: list[dict[str, Any]] = []
    trace: dict[str, Any] = {
        "papers": how,
        "skipped": skipped,
        "summaries_written": [str(d.document_id) for d in digests if not d.reused],
    }

    groups: list[dict[str, Any]] = []
    if kind == ReportKind.REVIEW:
        await progress("grouping", 0.62, "Grouping the research")
        async with session_factory() as session:
            grouped = await group_papers(session, settings, user_id, digests)
        groups = await name_groups(writer, grouped, abstracts, topic)
        await progress("analyzing", 0.66, "Comparing methods, data and results")
        chronology = chronology_section(digests, library)
        comparison = comparison_section(digests, groups, library, book)
    else:
        grouped = [digests]

    disagreements: list[dict[str, Any]] = []
    if kind in (ReportKind.REVIEW, ReportKind.DISAGREEMENTS, ReportKind.GAPS):
        await progress("disagreements", 0.7, "Looking for potential disagreements")
        found = find_disagreements(digests, library, verifier)
        disagreements = [describe(c, library, book) for c in found]

    gaps: list[dict[str, Any]] = []
    directions: list[dict[str, Any]] = []
    if kind in (ReportKind.REVIEW, ReportKind.GAPS):
        await progress("gaps", 0.74, "Identifying limitations and gaps")
        gap_items = await stated_gaps(settings, digests, book)
        gap_items += combination_gaps(digests, library, len(gap_items) + 1)
        gap_items += disagreement_gaps(disagreements, len(gap_items) + 1)
        gaps = [g.as_dict() for g in gap_items]
        if gap_items:
            await progress("gaps", 0.78, "Suggesting research directions")
            reply = await writer.generate(directions_messages(gap_items[:12]), "directions")
            directions = parse_directions(reply, gap_items[:12])

    if kind == ReportKind.REVIEW:
        await progress("writing", 0.8, "Writing the overview")
        overview_numbers = [
            n
            for d in digests
            for s in (d.of("contribution", "takeaway", "problem")[:1])
            for n in writer.book.cite(s)[:1]
        ][:10]
        subject = topic.strip() or "these papers"
        sections.append(
            await writer.section(
                "overview",
                "Overview",
                f"Write an introductory overview of {subject}: the problem these papers address "
                "and the main approaches they take.",
                overview_numbers,
            )
        )
        for index, group in enumerate(groups):
            await progress(
                "writing",
                0.82 + 0.13 * index / max(len(groups), 1),
                f"Writing about “{group['name']}”",
            )
            members = [d for d in digests if str(d.document_id) in group["document_ids"]]
            numbers = [
                n
                for d in members[:6]
                for s in d.of(*THEME_FIELDS)[:3]
                for n in writer.book.cite(s)[:2]
            ]
            section = await writer.section(
                f"theme-{group['id']}",
                group["name"],
                f"Write the review paragraph for the research theme “{group['name']}”"
                + (f" within {topic.strip()}" if topic.strip() else "")
                + ": what approach each paper takes, how the approaches differ, and what "
                "results they report.",
                numbers,
            )
            section["data"] = {
                "papers": [
                    {"id": str(d.document_id), "title": d.title, "year": d.year} for d in members
                ],
                "terms": group["terms"],
                "name_source": group["name_source"],
            }
            sections.append(section)
        sections += [chronology, comparison]
        if disagreements:
            sections.append(disagreements_section(disagreements))
        sections.append(gaps_section(gaps, directions))
    elif kind == ReportKind.GAPS:
        sections.append(gaps_section(gaps, directions))
    else:
        sections.append(disagreements_section(disagreements))

    await progress("verifying", 0.97, "Checking citations")
    support = support_summary(sections, verifier.name if verifier else "none")
    latency = round((time.perf_counter() - started) * 1000, 1)
    trace["calls"] = writer.trace
    trace["groups"] = groups
    async with session_factory() as session:
        report = await session.get(ResearchReport, report_id)
        if report is None:
            raise ReportGone
        report.sections = sections
        report.sources = book.items
        report.support = support
        report.document_ids = [str(d.document_id) for d in digests]
        report.trace = trace
        report.generation_config = {
            "llm_provider": provider_name(settings),
            "llm_model": writer.model or resolve_model(settings),
            "prompt_version": PROMPT_VERSION,
            "verifier": verifier.name if verifier else None,
            "embedding_model": settings.embedding_model,
            "depth": params.get("depth", "standard"),
        }
        report.input_tokens = writer.tokens["input"]
        report.output_tokens = writer.tokens["output"]
        report.latency_ms = latency
        report.status = ReportStatus.READY
        await session.commit()
    return {
        "report_id": str(report_id),
        "papers": len(digests),
        "sections": len(sections),
        "gaps": len(gaps),
        "disagreements": len(disagreements),
        "model_calls": writer.calls,
        "latency_ms": latency,
    }
