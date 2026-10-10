"""Deep Research: a bounded, inspectable research agent over the user's library.

    plan      → the model splits the request into 2–4 sub-questions
    for each  → search the library (hybrid retrieval) → answer from numbered passages,
                cited and checked → if the evidence wasn't enough: rewrite the question as a
                search query and try once more
    synthesis → a conclusion written from the passages the answers cited
    open      → sub-questions the library couldn't answer are reported as open, not guessed

Guard rails: one tool only (`search_papers`, read-only, scoped to the user's papers or the
chosen collection / papers), a maximum number of steps (model calls + searches), a token
budget and a wall-clock timeout. When a limit is hit the agent stops and writes up what it
has, saying which limit stopped it. Every step is recorded in the trace the UI shows.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.report import ReportStatus, ResearchReport
from app.services import organization as org
from app.services.analysis.digests import SourceBook
from app.services.analysis.writing import PROMPT_VERSION, Writer, support_summary
from app.services.llm import (
    INSUFFICIENT,
    GenerationParams,
    Message,
    get_llm,
    provider_name,
    resolve_model,
)
from app.services.rag.context import select_context
from app.services.rag.pipeline import get_verifier
from app.services.retrieval.service import SearchFilters, SearchRequest, search
from app.services.retrieval.types import SearchMode

MAX_SUBQUESTIONS = 4
MAX_STEPS = 16
TOKEN_BUDGET = 30_000
TIMEOUT_SECONDS = 15 * 60
TOOLS = ["search_papers: hybrid search over your papers (read-only)"]

# Measured with qwen2.5:3b on 3 requests: "2 to 4 sub-questions" gave 1, 1 and 4 (the single
# one dropped half of "How do LoRA and QLoRA …"); "exactly 3, numbered" gave 3, 3, 3.
PLAN_SYSTEM = """You plan research over a library of papers. Split the user's research request into exactly 3 focused sub-questions that together answer it and can each be answered from research papers.

Answer with the 3 sub-questions, numbered 1. 2. 3., one per line, and nothing else."""

QUERY_SYSTEM = """Rewrite the question as a short keyword search query (3 to 8 words) for searching research papers. Answer with the query only."""


class BudgetExceeded(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class Budget:
    max_steps: int = MAX_STEPS
    max_tokens: int = TOKEN_BUDGET
    timeout: float = TIMEOUT_SECONDS
    started: float = field(default_factory=time.perf_counter)
    steps: int = 0

    def spend(self, writer: Writer) -> None:
        """Call before every step; raises when a limit would be crossed."""
        if self.steps >= self.max_steps:
            raise BudgetExceeded(f"step limit ({self.max_steps}) reached")
        used = writer.tokens["input"] + writer.tokens["output"]
        if used >= self.max_tokens:
            raise BudgetExceeded(f"token budget ({self.max_tokens:,}) used up")
        if time.perf_counter() - self.started >= self.timeout:
            raise BudgetExceeded(f"time limit ({int(self.timeout // 60)} min) reached")
        self.steps += 1


_NUMBERING = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")


def parse_subquestions(reply: str, question: str) -> list[str]:
    found = []
    for line in reply.splitlines():
        text = _NUMBERING.sub("", line).strip().strip('"')
        if len(text.split()) >= 4 and not text.startswith(INSUFFICIENT[:30]):
            found.append(text)
    unique = list(dict.fromkeys(found))[:MAX_SUBQUESTIONS]
    return unique or [question]


def _source(result: Any) -> dict[str, Any]:
    chunk, document = result.chunk, result.document
    return {
        "chunk_id": str(chunk.id),
        "document": {
            "id": str(document.id),
            "title": document.title,
            "year": document.year,
            "authors_display": document.authors_display,
        },
        "section_title": chunk.section_title,
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "char_start": chunk.char_start,
        "boxes": chunk.boxes,
        "quote": chunk.text,
    }


async def run_deep_research(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    report_id: uuid.UUID,
    progress: Any,
) -> dict[str, Any]:
    from app.services.analysis.reports import ReportGone

    started = time.perf_counter()
    async with session_factory() as session:
        report = await session.get(ResearchReport, report_id)
        if report is None:
            raise ReportGone
        user_id, question, params = report.user_id, report.query, dict(report.params)
        scope: list[uuid.UUID] | None = None
        if params.get("document_ids"):
            scope = [uuid.UUID(d) for d in params["document_ids"]]
        elif params.get("collection_id"):
            scope = await org.collection_document_ids(session, uuid.UUID(params["collection_id"]))

    verifier = get_verifier(settings)
    book = SourceBook()
    writer = Writer(
        get_llm(settings),
        GenerationParams(settings.summary_max_tokens, settings.llm_temperature),
        verifier,
        book,
    )
    budget = Budget(
        max_steps=int(params.get("max_steps", MAX_STEPS)),
        max_tokens=int(params.get("token_budget", TOKEN_BUDGET)),
        timeout=float(params.get("timeout_seconds", TIMEOUT_SECONDS)),
    )
    steps: list[dict[str, Any]] = []
    stopped: str | None = None

    def record(action: str, **detail: Any) -> None:
        steps.append(
            {
                "step": len(steps) + 1,
                "action": action,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                "tokens_so_far": writer.tokens["input"] + writer.tokens["output"],
                **detail,
            }
        )

    async def search_papers(query: str) -> list[int]:
        """The agent's only tool: read-only, scoped to the user's (chosen) papers."""
        async with session_factory() as session:
            outcome = await search(
                session,
                settings,
                user_id,
                SearchRequest(
                    query,
                    SearchMode.HYBRID,
                    SearchFilters(document_ids=scope) if scope else SearchFilters(),
                    limit=settings.rerank_candidates,
                ),
            )
        selection = select_context(
            outcome.results,
            settings.context_token_budget,
            settings.context_max_passages,
            settings.context_min_relevance,
        )
        numbers = [book.add(_source(e.result)) for e in selection.evidence]
        record(
            "search",
            tool="search_papers",
            query=query,
            found=len(outcome.results),
            kept=len(numbers),
            papers=sorted({book.title(n) for n in numbers}),
        )
        return numbers

    subquestions: list[str] = [question]
    sections: list[dict[str, Any]] = []
    answered: list[dict[str, Any]] = []
    open_questions: list[str] = []
    try:
        # --- plan ----------------------------------------------------------------------------
        await progress("planning", 0.03, "Breaking the request into sub-questions")
        budget.spend(writer)
        reply = await writer.generate(
            [Message("system", PLAN_SYSTEM), Message("user", question)], "plan"
        )
        subquestions = parse_subquestions(reply, question)
        record("plan", subquestions=subquestions)

        # --- research each sub-question ------------------------------------------------------
        for index, sub in enumerate(subquestions):
            share = 0.85 / len(subquestions)
            await progress("researching", 0.08 + share * index, f"Researching: {sub[:90]}")
            budget.spend(writer)
            numbers = await search_papers(sub)
            budget.spend(writer)
            section = await writer.section(f"q{index + 1}", sub, sub, numbers)
            record("answer", question=sub, status=section["status"], cited=section["citations"])
            if section["status"] in ("insufficient", "unsupported"):
                # Not enough evidence: rewrite as a keyword query and search once more.
                budget.spend(writer)
                rewrite = await writer.generate(
                    [Message("system", QUERY_SYSTEM), Message("user", sub)], f"refine-{index + 1}"
                )
                lines = [line.strip().strip('"') for line in rewrite.splitlines() if line.strip()]
                query = lines[0][:200] if lines else ""
                if query and not query.startswith(INSUFFICIENT[:30]) and query != sub:
                    budget.spend(writer)
                    more = await search_papers(query)
                    record(
                        "refine",
                        question=sub,
                        query=query,
                        new_passages=len(set(more) - set(numbers)),
                    )
                    if set(more) - set(numbers):
                        budget.spend(writer)
                        section = await writer.section(
                            f"q{index + 1}", sub, sub, list(dict.fromkeys([*numbers, *more]))
                        )
                        record(
                            "answer",
                            question=sub,
                            status=section["status"],
                            cited=section["citations"],
                        )
            section["kind"] = "answer"
            sections.append(section)
            if section["status"] in ("insufficient", "unsupported") or not section["text"]:
                open_questions.append(sub)
            else:
                answered.append(section)
    except BudgetExceeded as exc:
        stopped = exc.reason
        record("stopped", reason=exc.reason)
        open_questions += [q for q in subquestions if q not in {s["title"] for s in sections}]

    # --- synthesis (allowed to run once even after a step limit, if time remains) -----------------
    synthesis = None
    cited = list(dict.fromkeys(n for s in answered for n in s["citations"]))[:14]
    if cited and time.perf_counter() - budget.started < budget.timeout:
        await progress("writing", 0.94, "Writing the conclusion")
        synthesis = await writer.section(
            "conclusion",
            "Findings",
            f"Answer the research request using the evidence: {question}",
            cited,
        )
        record("synthesize", status=synthesis["status"], cited=synthesis["citations"])
    ordered = ([synthesis] if synthesis else []) + sections
    if open_questions:
        ordered.append(
            {
                "key": "open",
                "title": "Open questions",
                "kind": "open",
                "text": "\n".join(f"- {q}" for q in open_questions),
                "data": {"questions": open_questions},
                "citations": [],
                "claims": [],
                "status": "derived",
                "label": "Your library had too little evidence to answer these",
                "origin": "derived",
            }
        )

    support = support_summary(ordered, verifier.name if verifier else "none")
    latency = round((time.perf_counter() - started) * 1000, 1)
    async with session_factory() as session:
        report = await session.get(ResearchReport, report_id)
        if report is None:
            raise ReportGone
        report.sections = ordered
        report.sources = book.items
        report.support = support
        report.document_ids = sorted({str(s["document"]["id"]) for s in book.items})
        report.trace = {
            "steps": steps,
            "calls": writer.trace,
            "tools": TOOLS,
            "limits": {
                "max_steps": budget.max_steps,
                "token_budget": budget.max_tokens,
                "timeout_seconds": budget.timeout,
            },
            "used": {
                "steps": budget.steps,
                "tokens": writer.tokens["input"] + writer.tokens["output"],
                "seconds": round(time.perf_counter() - budget.started, 1),
            },
            "stopped": stopped,
        }
        report.generation_config = {
            "llm_provider": provider_name(settings),
            "llm_model": writer.model or resolve_model(settings),
            "prompt_version": PROMPT_VERSION,
            "verifier": verifier.name if verifier else None,
        }
        report.input_tokens = writer.tokens["input"]
        report.output_tokens = writer.tokens["output"]
        report.latency_ms = latency
        report.status = ReportStatus.READY
        await session.commit()
    return {
        "report_id": str(report_id),
        "subquestions": len(subquestions),
        "open": len(open_questions),
        "steps": budget.steps,
        "stopped": stopped,
        "latency_ms": latency,
    }
