"""Answering a question with citations, as a stream of events.

    question ─→ understand ─→ search (hybrid + rerank) ─→ select context ─→ generate (stream)
             ─→ validate citations ─→ verify claims ─→ persist

Events (sent to the browser as server-sent events):
    status        {stage, detail}            understanding/searching/reading/writing/verifying
    query         {analysis}                 intent, entities, filters taken from the question
    evidence      {items}                    the numbered passages given to the model
    token         {text}                     answer text as it's generated
    answer        {text, citations, invalid} final text with only valid citations
    verification  {status, label, ...}       claim-level support
    done          {message_id, usage, timings_ms}
    error         {message, hint}

If nothing relevant is found the model is not called at all: the answer is the
fixed "insufficient evidence" sentence — the cheapest way to never hallucinate.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.errors import AppError, NotFoundError
from app.core.logging import get_logger
from app.core.metrics import metrics
from app.models.chat import ChatMessage, Citation, Conversation, ConversationScope, MessageStatus
from app.services.llm import (
    INSUFFICIENT,
    GenerationParams,
    LLMError,
    get_llm,
    provider_name,
    resolve_model,
)
from app.services.models.manager import model_manager
from app.services.rag.answer_cache import cache_fields, find_reusable
from app.services.rag.citations import split_claims, validate_citations
from app.services.rag.context import Evidence, select_context
from app.services.rag.prompt import PROMPT_VERSION, build_messages
from app.services.rag.query import analyze_query
from app.services.rag.verify import (
    LexicalVerifier,
    NLIVerifier,
    Verification,
    Verifier,
    summarize,
    verify_claims,
)
from app.services.retrieval import SearchFilters, SearchMode, SearchRequest, search
from app.services.usage import UsageScope

log = get_logger(__name__)
TRACE_STAGE_LIMIT = 10
# The reply was only a copied template placeholder ("<statement from passage 2> [2].").
EMPTY_REPLY = "The model's reply had no usable statements. Try asking again or rephrasing it."


def get_verifier(settings: Settings) -> Verifier | None:
    if settings.verifier_provider == "none":
        return None
    if settings.verifier_provider == "lexical":
        return LexicalVerifier()
    return NLIVerifier(settings.verifier_model, model_manager, settings.model_device)


def _evidence_item(evidence: Evidence) -> dict[str, Any]:
    result = evidence.result
    chunk, document = result.chunk, result.document
    return {
        "number": evidence.number,
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
        "score": round(result.score, 4),
    }


def _citation_status(number: int, support: dict[str, Any] | None) -> str | None:
    if support is None:
        return None
    statuses = [c["status"] for c in support["claims"] if number in c["citations"]]
    for status in ("supported", "partial", "unsupported"):
        if status in statuses:
            return status
    return None


async def load_history(
    session: AsyncSession, conversation_id: uuid.UUID, turns: int
) -> list[tuple[str, str]]:
    rows = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conversation_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(turns * 2 + 2)
        )
    ).scalars()
    messages = list(reversed(list(rows)))
    pairs: list[tuple[str, str]] = []
    for question, answer in pairwise(messages):
        if (
            question.role == "user"
            and answer.role == "assistant"
            and answer.status == MessageStatus.COMPLETE
        ):
            pairs.append((question.content, answer.content))
    return pairs[-turns:]


async def answer_question(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    question: str,
    fresh: bool = False,
) -> AsyncIterator[dict[str, Any]]:
    started = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        timings[name] = round((time.perf_counter() - since) * 1000, 1)
        return time.perf_counter()

    # --- conversation + user message ---------------------------------------------------------
    async with session_factory() as session:
        conversation = await session.get(Conversation, conversation_id)
        if conversation is None or conversation.user_id != user_id:
            raise NotFoundError("Conversation not found.")
        history = await load_history(session, conversation_id, settings.chat_history_turns)
        scope_ids = [uuid.UUID(d) for d in conversation.document_ids or []]
        papers_scope = conversation.scope == ConversationScope.PAPERS
        session.add(
            ChatMessage(
                conversation_id=conversation_id, user_id=user_id, role="user", content=question
            )
        )
        if conversation.title == "New conversation":
            conversation.title = question[:80] + ("…" if len(question) > 80 else "")
        conversation.last_message_at = datetime.now(UTC)
        await session.commit()

    parts: list[str] = []
    evidence: list[Evidence] = []
    trace: dict[str, Any] = {}
    usage = {"input_tokens": 0, "output_tokens": 0}
    verification: Verification | None = None
    support: dict[str, Any] | None = None
    status, error, final_text = MessageStatus.COMPLETE, None, ""
    generation_config = {
        "llm_provider": provider_name(settings),
        "llm_model": None,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "prompt_version": PROMPT_VERSION,
        "embedding_model": settings.embedding_model,
        "reranker": settings.reranker_model if settings.reranker_provider != "none" else None,
        "chunking_strategy": settings.chunking_strategy,
        "rrf_k": settings.rrf_k,
        "candidates_per_retriever": settings.top_k,
        "rerank_candidates": settings.rerank_candidates,
        "context_token_budget": settings.context_token_budget,
        "verifier": settings.verifier_provider,
        "answer_cache": cache_fields(question, len(history)),
    }

    try:
        # --- understand ----------------------------------------------------------------------
        mark = time.perf_counter()
        yield {"type": "status", "stage": "understanding", "detail": "Understanding the question"}
        analysis = analyze_query(question, history[-1][0] if history else None)
        trace["query"] = analysis.as_dict()
        yield {"type": "query", "analysis": analysis.as_dict()}
        mark = lap("understand", mark)

        # --- search --------------------------------------------------------------------------
        yield {"type": "status", "stage": "searching", "detail": "Searching your papers"}
        filters = SearchFilters(
            document_ids=scope_ids if papers_scope else None,
            year_from=analysis.year_from,
            year_to=analysis.year_to,
        )
        request = SearchRequest(
            analysis.retrieval_query,
            SearchMode.HYBRID,
            filters,
            limit=settings.rerank_candidates,
            debug=True,
        )
        async with session_factory() as session:
            outcome = await search(session, settings, user_id, request)
            if not outcome.results and (analysis.year_from or analysis.year_to):
                # A year filter that excludes everything is more likely a misreading than intent.
                request.filters = SearchFilters(document_ids=filters.document_ids)
                outcome = await search(session, settings, user_id, request)
                analysis.notes.append("No papers matched the year filter, so it was not applied")
                trace["query"] = analysis.as_dict()
            if (
                papers_scope
                and analysis.about_the_paper
                and outcome.reranker
                and outcome.results
                and all(r.score < settings.context_min_relevance for r in outcome.results)
            ):
                # The reranker judges word-level relevance, so "what is the main contribution?"
                # scores ~0 against every passage. The chat is already limited to these papers
                # and the question is about them, so use the keyword + meaning ranking instead.
                request.rerank = False
                outcome = await search(session, settings, user_id, request)
                analysis.notes.append(
                    "General question about the paper: passages ranked without the reranker"
                )
                trace["query"] = analysis.as_dict()
        trace["search"] = {
            "status": outcome.status,
            "retrievers": outcome.retrievers,
            "reranker": outcome.reranker,
            "searched_papers": outcome.searched_papers,
            "warnings": outcome.warnings,
            "timings_ms": outcome.timings_ms,
            "stages": {
                name: entries[:TRACE_STAGE_LIMIT]
                for name, entries in (outcome.trace or {}).get("stages", {}).items()
            },
        }
        mark = lap("search", mark)

        # --- select context ------------------------------------------------------------------
        yield {
            "type": "status",
            "stage": "reading",
            "detail": "Choosing the most relevant passages",
        }
        selection = select_context(
            outcome.results,
            settings.context_token_budget,
            settings.context_max_passages,
            settings.context_min_relevance,
        )
        evidence = selection.evidence
        trace["context"] = {"tokens": selection.tokens, "decisions": selection.decisions}
        yield {
            "type": "evidence",
            "items": [_evidence_item(e) for e in evidence],
            "reranker": outcome.reranker,  # scores are its probabilities when set
        }
        mark = lap("context", mark)

        # --- reuse an earlier answer (semantic answer cache) ----------------------------------
        reuse = None
        if not fresh and not history and evidence:
            async with session_factory() as session:
                reuse = await find_reusable(
                    session, settings, user_id, question, evidence,
                    resolve_model(settings), PROMPT_VERSION,
                )  # fmt: skip
        if reuse is not None:
            earlier = reuse.message
            # The same passages, numbered as the earlier answer cites them.
            by_chunk = {e.result.chunk.id: e for e in evidence}
            evidence = [
                replace(by_chunk[chunk_id], number=number)
                for number, chunk_id in enumerate(reuse.order, start=1)
            ]
            yield {
                "type": "evidence",
                "items": [_evidence_item(e) for e in evidence],
                "reranker": outcome.reranker,
            }
            reused = {
                "message_id": str(earlier.id),
                "conversation_id": str(earlier.conversation_id),
                "question": reuse.question,
                # SQLite returns naive datetimes; they are UTC.
                "asked_at": earlier.created_at.replace(
                    tzinfo=earlier.created_at.tzinfo or UTC
                ).isoformat(),
                "similarity": reuse.similarity,
            }
            yield {"type": "status", "stage": "reusing", "detail": "Reusing an earlier answer"}
            yield {"type": "reused", **reused}
            generation_config["llm_model"] = (earlier.generation_config or {}).get("llm_model")
            generation_config["reused_from"] = reused
            trace["reused_from"] = reused
            final_text = earlier.content
            check = validate_citations(final_text, len(evidence))
            yield {"type": "answer", "text": final_text, "cited": check.cited,
                   "invalid_citations": check.invalid}  # fmt: skip
            support = earlier.support
            if support is not None:
                yield {"type": "verification", **support}
            metrics.inc("answer_cache_total", result="reused")
            lap("reuse", mark)
        else:
            if not fresh and not history and evidence and settings.answer_cache_enabled:
                metrics.inc("answer_cache_total", result="miss")
            # --- generate ------------------------------------------------------------------------
            if not evidence:
                parts.append(INSUFFICIENT)
                yield {"type": "token", "text": INSUFFICIENT}
                generation_config["llm_model"] = None
            else:
                llm = get_llm(settings, UsageScope(user_id, "chat"))
                generation_config["llm_model"] = resolve_model(settings)
                yield {"type": "status", "stage": "writing", "detail": "Writing the answer"}
                messages = build_messages(question, evidence, history)
                params = GenerationParams(settings.llm_max_tokens, settings.llm_temperature)
                first_token = None
                async for event in llm.stream(messages, params):
                    if event.text:
                        if first_token is None:
                            first_token = time.perf_counter()
                            timings["first_token"] = round((first_token - started) * 1000, 1)
                        parts.append(event.text)
                        yield {"type": "token", "text": event.text}
                    if event.done:
                        usage = {
                            "input_tokens": event.usage.input_tokens,
                            "output_tokens": event.usage.output_tokens,
                        }
                        if event.model:
                            generation_config["llm_model"] = event.model
            mark = lap("generate", mark)

            # --- citations + verification --------------------------------------------------------
            check = validate_citations("".join(parts), len(evidence))
            final_text = check.text or (EMPTY_REPLY if "".join(parts).strip() else "")
            insufficient = final_text.startswith(INSUFFICIENT[:40])
            yield {
                "type": "answer",
                "text": final_text,
                "cited": check.cited,
                "invalid_citations": check.invalid,
            }
            verifier = get_verifier(settings) if not insufficient else None
            if verifier is not None and evidence:
                yield {"type": "status", "stage": "verifying", "detail": "Checking each claim"}
                claims = split_claims(final_text)
                passages = {e.number: e.result.chunk.text for e in evidence}
                results = await asyncio.to_thread(verify_claims, verifier, claims, passages)
                verification = summarize(results, verifier.name, insufficient=False)
            elif insufficient:
                verification = summarize([], "none", insufficient=True)
            if verification is not None:
                support = _verification_dict(verification)
                yield {"type": "verification", **support}
            lap("verify", mark)
    except (LLMError, AppError) as exc:
        status = MessageStatus.ERROR
        message = exc.user_message if isinstance(exc, LLMError) else exc.message
        hint = exc.detail if isinstance(exc, LLMError) else exc.hint
        error = message
        final_text = "".join(parts)
        log.warning("answer_failed", error=message, detail=hint)
        yield {"type": "error", "message": message, "hint": hint}
    except (asyncio.CancelledError, GeneratorExit):
        status, error, final_text = MessageStatus.STOPPED, None, "".join(parts)
        await asyncio.shield(
            _persist(session_factory, conversation_id, user_id, final_text, status, error,
                     evidence, [], support, trace, generation_config, usage, started)
        )  # fmt: skip
        raise

    cited = validate_citations(final_text, len(evidence)).cited if final_text else []
    message_id = await _persist(
        session_factory, conversation_id, user_id, final_text, status, error, evidence, cited,
        support, trace, generation_config, usage, started,
    )  # fmt: skip
    timings["total"] = round((time.perf_counter() - started) * 1000, 1)
    metrics.inc("chat_answers_total", status=str(status))
    metrics.observe("chat_latency_ms", timings["total"])
    yield {"type": "done", "message_id": str(message_id), "usage": usage, "timings_ms": timings}


def _verification_dict(verification: Verification) -> dict[str, Any]:
    return {
        "status": verification.status,
        "label": verification.label,
        "explanation": verification.explanation,
        "verifier": verification.verifier,
        "claims": [
            {
                "text": c.text,
                "citations": c.citations,
                "status": c.status,
                "entailment": c.entailment,
                "best_passage": c.best_passage,
                "found_in": c.found_in,
            }
            for c in verification.claims
        ],
    }


async def _persist(
    session_factory: async_sessionmaker[AsyncSession],
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    text: str,
    status: str,
    error: str | None,
    evidence: list[Evidence],
    cited: list[int],
    support: dict[str, Any] | None,
    trace: dict[str, Any],
    generation_config: dict[str, Any],
    usage: dict[str, int],
    started: float,
) -> uuid.UUID:
    async with session_factory() as session:
        message = ChatMessage(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=text,
            status=status,
            error=error,
            support=support,
            retrieval_trace=trace,
            generation_config=generation_config,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )
        session.add(message)
        await session.flush()
        for item in evidence:
            result = item.result
            session.add(
                Citation(
                    message_id=message.id,
                    number=item.number,
                    chunk_id=result.chunk.id,
                    document_id=result.document.id,
                    document_title=result.document.title,
                    year=result.document.year,
                    section_title=result.chunk.section_title,
                    page_start=result.chunk.page_start,
                    page_end=result.chunk.page_end,
                    char_start=result.chunk.char_start,
                    quote=result.chunk.text,
                    boxes=result.chunk.boxes,
                    score=result.score,
                    cited=item.number in cited,
                    support_status=_citation_status(item.number, support),
                )
            )
        conversation = await session.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.last_message_at = datetime.now(UTC)
        await session.commit()
        return message.id
