"""Executes one watch run: search arXiv, score candidates, record a digest, optionally import
and attach to a collection, and notify. Runs outside a request (a scheduler tick enqueues the
job that calls this), so — unlike a request handler — it must commit and dispatch any jobs it
enqueues itself; see the `run_after_commit` call at the end of the write phase.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.database import run_after_commit
from app.core.errors import AppError, ConflictError
from app.core.logging import get_logger
from app.models.agent import AgentDigestEntry, AgentRun, AgentWatch, ImportStatus, RunStatus
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus
from app.models.report import ReportKind
from app.services import arxiv, notifications, webhooks
from app.services import organization as org
from app.services.agent import relevance
from app.services.agent.service import document_id_for_arxiv_id
from app.services.analysis.reports import MIN_PAPERS
from app.services.analysis.service import request_report
from app.services.documents import DocumentService
from app.services.jobs import JobService
from app.services.llm import (
    GenerationParams,
    LLMError,
    Message,
    get_llm,
    llm_status,
    on_free_tier,
)
from app.services.storage import get_storage
from app.services.summaries.engine import complete
from app.workers.dispatcher import get_dispatcher

log = get_logger(__name__)

Report = Callable[[str, float, str | None], Awaitable[None]]
SYNTHESIS_POLL_SECONDS = 3.0
SYNTHESIS_WAIT_TIMEOUT_SECONDS = 300.0


async def _advance_schedule(watch: AgentWatch, settings: Settings, searched_at: datetime) -> None:
    watch.last_searched_at = searched_at
    watch.next_run_at = utcnow() + timedelta(
        hours=max(watch.interval_hours, settings.agent_watch_min_interval_hours)
    )


def _blurb_prompt(watch: AgentWatch, candidate: arxiv.ArxivCandidate) -> str:
    return (
        f"In one short sentence, say why this paper may be relevant to someone watching for "
        f'"{watch.query}". Paper title: {candidate.title}\nAbstract: {candidate.abstract[:800]}'
    )


async def _wait_for_ready(
    session_factory: async_sessionmaker[AsyncSession],
    document_ids: list[uuid.UUID],
    report: Report,
) -> list[uuid.UUID]:
    """Poll until each document leaves QUEUED/PROCESSING, bounded by a timeout. Returns the
    ones that reached READY; a FAILED or still-unfinished document is dropped, not retried."""
    deadline = time.monotonic() + SYNTHESIS_WAIT_TIMEOUT_SECONDS
    remaining = set(document_ids)
    ready: list[uuid.UUID] = []
    while remaining and time.monotonic() < deadline:
        async with session_factory() as session:
            rows = await session.execute(
                select(Document.id, Document.status).where(Document.id.in_(remaining))
            )
            for doc_id, doc_status in rows.all():
                if doc_status == DocumentStatus.READY:
                    ready.append(doc_id)
                    remaining.discard(doc_id)
                elif doc_status == DocumentStatus.FAILED:
                    remaining.discard(doc_id)
        if remaining:
            await report(
                "synthesizing", 0.95, f"Waiting for {len(remaining)} paper(s) to finish processing"
            )
            await asyncio.sleep(SYNTHESIS_POLL_SECONDS)
    return ready


async def _request_synthesis_report(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: uuid.UUID,
    query: str,
    document_ids: list[uuid.UUID],
) -> uuid.UUID | None:
    if len(document_ids) < MIN_PAPERS[ReportKind.REVIEW]:
        return None
    async with session_factory() as session:
        jobs = JobService(session, get_dispatcher(settings))
        try:
            report = await request_report(
                session,
                settings,
                jobs,
                user_id,
                ReportKind.REVIEW,
                query=query,
                document_ids=document_ids,
            )
        except AppError as exc:
            # No LLM configured, etc. — synthesis is best-effort, never a run failure.
            log.info("agent_synthesis_skipped", user_id=str(user_id), reason=exc.message)
            return None
        await session.commit()
        run_after_commit(session)
        return report.id


async def execute_run(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    run_id: uuid.UUID,
    report: Report,
) -> dict[str, Any]:
    async with session_factory() as session:
        run = await session.get(AgentRun, run_id)
        if run is None:
            return {"status": "deleted"}
        watch = await session.get(AgentWatch, run.watch_id)
        if watch is None:
            run.status = RunStatus.FAILED
            run.error_message = "The watch was deleted."
            run.finished_at = utcnow()
            await session.commit()
            return {"status": "watch_deleted"}
        run.status = RunStatus.RUNNING
        run.started_at = utcnow()
        watch_id, user_id = watch.id, watch.user_id
        query, collection_id = watch.query, watch.collection_id
        threshold = watch.relevance_threshold
        since = watch.last_searched_at
        lookback_days = settings.agent_watch_lookback_days
        await session.commit()

    await report("searching", 0.05, "Searching arXiv")
    search_started = utcnow()
    search_since = since or (search_started - timedelta(days=lookback_days))
    try:
        candidates = await arxiv.search(
            settings,
            query,
            since=search_since,
            max_results=max(settings.agent_watch_max_results_per_run * 3, 25),
        )
    except AppError as exc:
        async with session_factory() as session:
            run = await session.get(AgentRun, run_id)
            watch = await session.get(AgentWatch, watch_id)
            if run is not None:
                run.status = RunStatus.SUCCEEDED
                run.error_message = f"Skipped: {exc.message}"
                run.finished_at = utcnow()
            if watch is not None:
                await _advance_schedule(watch, settings, search_started)
            await session.commit()
        return {"status": "skipped", "reason": exc.message}

    await report("scoring", 0.25, f"Scoring {len(candidates)} candidates")
    async with session_factory() as session:
        watch = await session.get(AgentWatch, watch_id)
        assert watch is not None
        topic, project_question = await relevance.anchor_text(session, watch)
    anchor = relevance.anchor_vector(settings, topic, project_question)
    scores = relevance.score_candidates(
        settings, anchor, [c.abstract or c.title for c in candidates]
    )
    ranked = sorted(zip(candidates, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    kept = [(candidate, float(score)) for candidate, score in ranked if score >= threshold][
        : settings.agent_watch_max_results_per_run
    ]

    llm = None
    status = await llm_status(settings)
    if status.get("ready") and not on_free_tier(settings):
        llm = get_llm(settings)

    imported = 0
    entries_by_arxiv_id: dict[str, AgentDigestEntry] = {}
    async with session_factory() as session:
        run = await session.get(AgentRun, run_id)
        watch = await session.get(AgentWatch, watch_id)
        assert run is not None and watch is not None
        jobs = JobService(session, get_dispatcher(settings))
        documents = DocumentService(session, settings, get_storage(settings), jobs)
        for index, (candidate, score) in enumerate(kept):
            fraction = 0.3 + 0.6 * (index / max(len(kept), 1))
            await report("reviewing", fraction, f"Reviewing {index + 1} of {len(kept)}")
            blurb: str | None = None
            if llm is not None:
                try:
                    result = await complete(
                        llm,
                        [Message("user", _blurb_prompt(watch, candidate))],
                        GenerationParams(max_tokens=60, temperature=0.2),
                    )
                    blurb = result.text.strip() or None
                except LLMError:
                    blurb = None
            entry = AgentDigestEntry(
                run_id=run.id,
                watch_id=watch.id,
                arxiv_id=candidate.arxiv_id,
                title=candidate.title,
                authors=candidate.authors,
                abstract=candidate.abstract,
                published=candidate.published,
                score=score,
                blurb=blurb,
                import_status=ImportStatus.PENDING,
                trace={
                    "search_query": query,
                    "searched_since": search_since.isoformat(),
                    "anchor_topic": topic,
                    "anchor_project_question": project_question,
                    "rank": index + 1,
                    "candidates_in_run": len(candidates),
                    "relevance_threshold": threshold,
                },
            )
            if watch.auto_import:
                try:
                    document = await documents.import_arxiv(user_id, candidate.arxiv_id)
                except ConflictError:
                    entry.document_id = await document_id_for_arxiv_id(
                        session, user_id, candidate.arxiv_id
                    )
                    entry.import_status = ImportStatus.ALREADY_IN_LIBRARY
                else:
                    entry.document_id = document.id
                    entry.import_status = ImportStatus.IMPORTED
                    imported += 1
                    if collection_id is not None:
                        collection = await org.get_collection(session, user_id, collection_id)
                        await org.add_to_collection(session, user_id, collection, [document.id])
            entries_by_arxiv_id[candidate.arxiv_id] = entry
            session.add(entry)

        synthesis_document_ids: list[uuid.UUID] = []
        if watch.synthesize and len(kept) >= settings.agent_watch_synthesis_min_papers:
            await report("importing", 0.92, "Importing matches for synthesis")
            for candidate, _score in kept[: settings.agent_watch_synthesis_max_papers]:
                entry = entries_by_arxiv_id[candidate.arxiv_id]
                doc_id = entry.document_id  # already imported above (auto_import was on)
                if doc_id is None:
                    try:
                        document = await documents.import_arxiv(user_id, candidate.arxiv_id)
                        doc_id = document.id
                        entry.document_id = doc_id
                        entry.import_status = ImportStatus.IMPORTED
                        imported += 1
                        if collection_id is not None:
                            collection = await org.get_collection(session, user_id, collection_id)
                            await org.add_to_collection(session, user_id, collection, [doc_id])
                    except ConflictError:
                        doc_id = await document_id_for_arxiv_id(
                            session, user_id, candidate.arxiv_id
                        )
                        entry.document_id = doc_id
                        entry.import_status = ImportStatus.ALREADY_IN_LIBRARY
                if doc_id is not None:
                    synthesis_document_ids.append(doc_id)

        # Not SUCCEEDED yet: synthesis (import wait + review request) still runs below, outside
        # this session, and the run must stay "running" until that's actually done too — a
        # client polling the run would otherwise see "succeeded" while a review is still
        # pending, and have no way to tell a finished run from one that's still working.
        run.searched_since = search_since
        run.candidates_found = len(candidates)
        run.candidates_above_threshold = len(kept)
        run.imported_count = imported
        await _advance_schedule(watch, settings, search_started)
        webhook_text = None
        if kept:
            plural = "s" if len(kept) != 1 else ""
            title = f'Found {len(kept)} new paper{plural} for "{watch.name}"'
            await notifications.create(
                session,
                user_id,
                kind="agent_watch_digest",
                title=title,
                body=", ".join(c.title for c, _ in kept[:3]),
                link=f"/watches/{watch.id}",
            )
            link = f"{settings.app_base_url}/watches/{watch.id}" if settings.app_base_url else ""
            webhook_text = f"{title}\n{link}" if link else title
        await session.commit()
        # Outside a request: nothing calls this automatically. Without it, any document.process
        # job enqueued by import_arxiv above is registered but never dispatched.
        run_after_commit(session)

    if webhook_text is not None:
        # Kept outside the write-phase session: a slow or failing webhook POST must never
        # affect the DB transaction above, which has already committed by this point.
        await webhooks.notify_user(session_factory, user_id, webhook_text)

    report_id = None
    if synthesis_document_ids:
        # Does not block on the review finishing — only on the papers being readable. The
        # review itself runs as its own `report.generate` job, exactly like a user-requested one.
        ready_ids = await _wait_for_ready(session_factory, synthesis_document_ids, report)
        report_id = await _request_synthesis_report(
            session_factory, settings, user_id, query, ready_ids
        )

    async with session_factory() as session:
        run = await session.get(AgentRun, run_id)
        if run is not None:
            run.status = RunStatus.SUCCEEDED
            run.finished_at = utcnow()
            run.report_id = report_id
            await session.commit()

    return {
        "status": "succeeded",
        "found": len(candidates),
        "kept": len(kept),
        "imported": imported,
        "report_id": str(report_id) if report_id else None,
    }
