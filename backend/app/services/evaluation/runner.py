"""Running an evaluation: one configuration over a dataset's verified questions.

Retrieval runs search each question with the run's configuration and score the ranked
passages (`metrics.py`). RAG runs also answer each question with the normal pipeline pieces
(context selection → prompt → model → citation validation → claim verification) and score:

- **Context recall / context precision**: expected spans covered by the passages given to the
  model / share of those passages that are relevant.
- **Faithfulness**: share of the answer's claims the entailment model supports (partial = ½);
  "insufficient evidence" answers are counted separately, not as unfaithful.
- **Citation correctness**: share of cited claims whose cited passage supports them.
- **Answer relevance**: cosine similarity of question and answer embeddings — a cheap proxy,
  not a judgement of correctness (stated in the UI). No LLM grades another LLM here.

System figures per run: latency (search, generation, check; p50 / p95), tokens, cost from
the configured prices, throughput.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.document import Document, DocumentStatus, DocumentVersion
from app.models.evaluation import EvalItem, EvalRun
from app.services.embeddings import get_embedding_provider
from app.services.evaluation.metrics import (
    Passage,
    Span,
    covers,
    mean,
    percentile,
    retrieval_metrics,
)
from app.services.llm import INSUFFICIENT, GenerationParams, get_llm, resolve_model
from app.services.rag.citations import split_claims, validate_citations
from app.services.rag.context import select_context
from app.services.rag.pipeline import get_verifier
from app.services.rag.prompt import build_messages
from app.services.rag.verify import verify_claims
from app.services.retrieval.service import SearchFilters, SearchRequest, search
from app.services.retrieval.types import SearchMode
from app.services.summaries.engine import complete

Report = Callable[[str, float, str | None], Awaitable[None]]
KS = (1, 3, 5, 10)
MAX_RAG_ITEMS = 25  # each answer is a model call (about 20-60 s on a CPU)


class RunGone(Exception):
    pass


def run_settings(settings: Settings, config: dict[str, Any]) -> Settings:
    """The app's settings with this run's retrieval knobs applied."""
    return settings.model_copy(
        update={
            k: config[k]
            for k in ("rrf_k", "top_k", "rerank_candidates", "context_max_passages")
            if config.get(k) is not None
        }
    )


async def index_description(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """What the user's index was built with (recorded with every run)."""
    rows = (
        await session.execute(
            select(DocumentVersion.embedding_model, DocumentVersion.chunking_strategy, func.count())
            .join(Document, Document.current_version_id == DocumentVersion.id)
            .where(Document.user_id == user_id, Document.status == DocumentStatus.READY)
            .group_by(DocumentVersion.embedding_model, DocumentVersion.chunking_strategy)
        )
    ).all()
    return {
        "papers": sum(count for *_, count in rows),
        "embedding_models": sorted({m for m, _, _ in rows if m}),
        "chunking_strategies": sorted({c for _, c, _ in rows if c}),
    }


def _spans(item: EvalItem) -> list[Span]:
    return [
        Span(
            str(e["document_id"]),
            str(e.get("version_id", "")),
            int(e["char_start"]),
            int(e["char_end"]),
            str(e.get("quote", "")),
        )
        for e in item.expected
    ]


def _passage(result: Any) -> Passage:
    return Passage(
        str(result.document.id),
        str(result.chunk.version_id),
        result.chunk.char_start,
        result.chunk.char_end,
        result.chunk.text,
    )


async def run_evaluation(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    run_id: uuid.UUID,
    report: Report,
) -> dict[str, Any]:
    started = time.perf_counter()
    async with session_factory() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            raise RunGone
        run.status = "running"
        await session.commit()
        user_id, kind, config = run.user_id, run.kind, dict(run.config)
        items = list(
            (
                await session.execute(
                    select(EvalItem)
                    .where(EvalItem.dataset_id == run.dataset_id, EvalItem.status == "verified")
                    .order_by(EvalItem.created_at)
                )
            ).scalars()
        )
        for item in items:
            session.expunge(item)
        index = await index_description(session, user_id)
    if kind == "rag":
        items = items[:MAX_RAG_ITEMS]
    s = run_settings(settings, config)
    mode = SearchMode(config.get("mode", "hybrid"))
    rerank = bool(config.get("rerank", True)) and settings.reranker_provider != "none"
    verifier = get_verifier(settings) if kind == "rag" else None
    llm = get_llm(settings) if kind == "rag" else None
    embedder = get_embedding_provider(settings) if kind == "rag" else None
    params = GenerationParams(settings.llm_max_tokens, settings.llm_temperature)

    rows: list[dict[str, Any]] = []
    per_item: list[dict[str, Any]] = []
    search_ms: list[float] = []
    total_ms: list[float] = []
    tokens = {"input": 0, "output": 0}
    model_name: str | None = None
    for position, item in enumerate(items):
        await report(
            "evaluating",
            position / max(len(items), 1),
            f"Question {position + 1} of {len(items)}",
        )
        spans = _spans(item)
        mark = time.perf_counter()
        async with session_factory() as session:
            outcome = await search(
                session,
                s,
                user_id,
                SearchRequest(
                    item.question,
                    mode,
                    SearchFilters(),
                    limit=max(KS) if kind == "retrieval" else s.rerank_candidates,
                    rerank=rerank,
                ),
            )
        searched = round((time.perf_counter() - mark) * 1000, 1)
        search_ms.append(searched)
        passages = [_passage(r) for r in outcome.results]
        row: dict[str, Any] = retrieval_metrics(passages, spans, KS)
        entry: dict[str, Any] = {
            "item_id": str(item.id),
            "question": item.question,
            "metrics": row,
            "top": [
                {
                    "title": r.document.title,
                    "page": r.chunk.page_start,
                    "relevant": any(covers(passages[i], sp) for sp in spans),
                }
                for i, r in enumerate(outcome.results[:5])
            ],
            "latency_ms": {"search": searched},
        }
        if kind == "rag":
            assert llm is not None and embedder is not None
            selection = select_context(
                outcome.results,
                s.context_token_budget,
                s.context_max_passages,
                s.context_min_relevance,
            )
            context = [_passage(e.result) for e in selection.evidence]
            row["context_recall"] = retrieval_metrics(context, spans, (len(context) or 1,))[
                f"recall@{len(context) or 1}"
            ]
            row["context_precision"] = (
                sum(1 for p in context if any(covers(p, sp) for sp in spans)) / len(context)
                if context
                else 0.0
            )
            mark = time.perf_counter()
            answer = INSUFFICIENT
            if selection.evidence:
                result = await complete(
                    llm, build_messages(item.question, selection.evidence, []), params
                )
                answer = result.text
                tokens["input"] += result.input_tokens
                tokens["output"] += result.output_tokens
                model_name = result.model or model_name
            generated = round((time.perf_counter() - mark) * 1000, 1)
            check = validate_citations(answer, len(selection.evidence))
            insufficient = check.text.startswith(INSUFFICIENT[:40])
            mark = time.perf_counter()
            row["insufficient"] = 1.0 if insufficient else 0.0
            if not insufficient and verifier is not None:
                claims = split_claims(check.text)
                passages_text = {e.number: e.result.chunk.text for e in selection.evidence}
                titles = {e.number: e.result.document.title for e in selection.evidence}
                checked = await asyncio.to_thread(
                    verify_claims, verifier, claims, passages_text, titles
                )
                if checked:
                    # As in chat's verdict: a claim backed by any passage is faithful even if
                    # it cites the wrong one or none (that is citation correctness's job).
                    score = {"supported": 1.0, "partial": 0.5}
                    row["faithfulness"] = round(
                        sum(
                            1.0 if c.found_in is not None else score.get(c.status, 0.0)
                            for c in checked
                        )
                        / len(checked),
                        4,
                    )
                    cited = [c for c in checked if c.citations]
                    row["citation_correctness"] = (
                        round(
                            sum(1 for c in cited if c.status in ("supported", "partial"))
                            / len(cited),
                            4,
                        )
                        if cited
                        else 0.0
                    )
                q = await asyncio.to_thread(embedder.embed_query, item.question)
                a = (await asyncio.to_thread(embedder.embed_documents, [check.text]))[0]
                row["answer_relevance"] = round(
                    float(np.dot(q, a) / (np.linalg.norm(q) * np.linalg.norm(a) or 1.0)), 4
                )
            verified = round((time.perf_counter() - mark) * 1000, 1)
            entry["answer"] = check.text[:2000]
            entry["latency_ms"] |= {"generate": generated, "verify": verified}
        total_ms.append(round(sum(entry["latency_ms"].values()), 1))
        rows.append(row)
        per_item.append(entry)

    elapsed = time.perf_counter() - started
    aggregates: dict[str, Any] = dict(mean(rows))
    cost = (
        tokens["input"] * settings.llm_price_input_per_million
        + tokens["output"] * settings.llm_price_output_per_million
    ) / 1_000_000
    aggregates |= {
        "questions": len(items),
        "latency_search_p50_ms": percentile(search_ms, 0.5),
        "latency_search_p95_ms": percentile(search_ms, 0.95),
        "latency_total_p50_ms": percentile(total_ms, 0.5),
        "latency_total_p95_ms": percentile(total_ms, 0.95),
        "throughput_per_min": round(len(items) / (elapsed / 60), 2) if elapsed > 0 else None,
        "tokens_input": tokens["input"],
        "tokens_output": tokens["output"],
        "cost_usd": round(cost, 6),
    }
    async with session_factory() as session:
        run = await session.get(EvalRun, run_id)
        if run is None:
            raise RunGone
        run.metrics = aggregates
        run.per_item = per_item
        run.items_evaluated = len(items)
        run.latency_ms = round(elapsed * 1000, 1)
        run.config = {
            **run.config,
            "index": index,
            "reranker": settings.reranker_model if rerank else None,
            "llm_model": (model_name or resolve_model(settings)) if kind == "rag" else None,
            "verifier": verifier.name if verifier else None,
        }
        run.status = "ready"
        await session.commit()
    return {"run_id": str(run_id), "questions": len(items), "metrics": aggregates}
