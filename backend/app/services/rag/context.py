"""Choosing the evidence the model sees — never "everything retrieved".

1. Relevance floor: passages the reranker scores below CONTEXT_MIN_RELEVANCE are dropped.
2. Near-duplicates: the same text from a re-upload or another format of the same paper
   (Jaccard ≥ 0.8 over analyzed terms) is kept once.
3. MMR (maximal marginal relevance, λ = 0.7): each next passage maximizes
   λ·relevance − (1−λ)·max similarity to what's already chosen, so five near-identical
   passages don't crowd out a second source.
4. Token budget: passages are packed until CONTEXT_TOKEN_BUDGET / CONTEXT_MAX_PASSAGES.

Every decision is recorded so the UI can show why a passage was or wasn't used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.llm import count_tokens
from app.services.retrieval import PassageResult
from app.services.retrieval.text import analyze

MMR_LAMBDA = 0.7
DUPLICATE_JACCARD = 0.8


@dataclass
class Evidence:
    number: int  # [n] in the prompt and the answer
    result: PassageResult
    tokens: int


@dataclass
class ContextSelection:
    evidence: list[Evidence]
    decisions: list[dict[str, Any]] = field(default_factory=list)
    tokens: int = 0


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def select_context(
    results: list[PassageResult],
    token_budget: int,
    max_passages: int,
    min_relevance: float,
) -> ContextSelection:
    decisions: list[dict[str, Any]] = []

    def decide(result: PassageResult, outcome: str, reason: str) -> None:
        decisions.append(
            {
                "chunk_id": str(result.chunk.id),
                "document_title": result.document.title,
                "section_title": result.chunk.section_title,
                "page": result.chunk.page_start,
                "score": round(result.score, 4),
                "outcome": outcome,
                "reason": reason,
            }
        )

    candidates: list[PassageResult] = []
    for result in results:
        if result.score_kind == "rerank" and result.score < min_relevance:
            decide(result, "dropped", f"relevance {result.score:.3f} below {min_relevance}")
        else:
            candidates.append(result)

    top = max((r.score for r in candidates), default=0.0) or 1.0
    terms = {id(r): set(analyze(r.chunk.text)) for r in candidates}
    chosen: list[PassageResult] = []
    used_tokens = 0
    remaining = list(candidates)
    while remaining and len(chosen) < max_passages:

        def mmr(result: PassageResult) -> float:
            similarity = max((_jaccard(terms[id(result)], terms[id(c)]) for c in chosen), default=0)
            return MMR_LAMBDA * (result.score / top) - (1 - MMR_LAMBDA) * similarity

        best = max(remaining, key=mmr)
        best_mmr = mmr(best)
        remaining.remove(best)
        duplicate = next(
            (c for c in chosen if _jaccard(terms[id(best)], terms[id(c)]) >= DUPLICATE_JACCARD),
            None,
        )
        if duplicate is not None:
            decide(
                best, "dropped", f"near-duplicate of a passage from “{duplicate.document.title}”"
            )
            continue
        tokens = count_tokens(best.chunk.text)
        if used_tokens + tokens > token_budget and chosen:
            decide(best, "dropped", "token budget reached")
            continue
        chosen.append(best)
        used_tokens += tokens
        decide(best, "used", f"selected (MMR {best_mmr:.3f})")
    for result in remaining:
        decide(result, "dropped", "enough passages selected")

    return ContextSelection(
        evidence=[
            Evidence(number=i, result=r, tokens=count_tokens(r.chunk.text))
            for i, r in enumerate(chosen, start=1)
        ],
        decisions=decisions,
        tokens=used_tokens,
    )
