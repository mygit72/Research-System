"""Semantic answer cache: reuse an earlier answer to a near-identical question.

An answer takes 20-90 s on a CPU; asking the same thing twice is common. But question
similarity alone is unsafe. Measured with bge-small on question pairs:

- "Does DPR outperform BM25?" vs "Does BM25 outperform DPR?" → cosine 0.990 (opposite!)
- "… Table 2?" vs "… Table 3?" → 0.927;  "… 65B model?" vs "… 33B model?" → 0.913
- while a real paraphrase ("What does ColBERT contribute?") can score 0.846.

So an earlier answer is reused only when all of these hold:

1. it was written from the *same passages* — so the library hasn't changed in a way that
   matters and the earlier claim check is still valid. (Not necessarily in the same order:
   near-tied reranker scores swap places when only the question's wording changes. The
   reused answer is shown with the passages in its own order, so its [n] still match.)
2. the same model, prompt version and verifier wrote and checked it;
3. both questions started a conversation (follow-ups depend on the history);
4. the earlier answer passed its check (well or partially supported): a cache must not
   spread an answer that failed — asking again may get a better one;
5. question embeddings have cosine ≥ `ANSWER_CACHE_MIN_SIMILARITY` (0.95) *and* the same
   key tokens in the same order — numbers and names (QLoRA, BM25, 65B, Table 2), whichever
   way the user capitalized them.

On the probe set this rejected all 10 different-answer pairs and reused 5 of 8 paraphrases
(a miss only costs a fresh answer). The reused answer is labelled, with "Answer again".
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.chat import ChatMessage, Citation, MessageStatus
from app.services.embeddings import get_embedding_provider
from app.services.rag.context import Evidence
from app.services.retrieval.dense import embed_query

# Only answers whose claims the checker supported are reused (higher = preferred).
REUSABLE = {"supported": 2, "partial": 1}

_TOKEN = re.compile(r"[A-Za-z0-9][\w.\-]*[A-Za-z0-9]|[A-Za-z0-9]")


def _is_key(token: str, index: int) -> bool:
    return (
        any(c.isdigit() for c in token)
        or any(c.isupper() for c in token[1:])
        or (index > 0 and token[0].isupper())
    )


def key_tokens(question: str) -> list[str]:
    """Numbers and names, in order: tokens with a digit, an inner capital, or a capital
    that isn't the first word ("What", "How" start questions; "Natural", "QLoRA" don't)."""
    return [t.casefold() for i, t in enumerate(_TOKEN.findall(question)) if _is_key(t, i)]


def same_key_tokens(a: str, b: str) -> bool:
    """Same numbers and names in the same order. A name written in capitals in either
    question counts in both, so "GPU" and "gpu" match but "QLoRA" and "LoRA" don't."""
    keys = set(key_tokens(a)) | set(key_tokens(b))
    words_a = [t.casefold() for t in _TOKEN.findall(a)]
    words_b = [t.casefold() for t in _TOKEN.findall(b)]
    return [w for w in words_a if w in keys] == [w for w in words_b if w in keys]


def cache_fields(question: str, history_turns: int) -> dict[str, Any]:
    """Stored in the answer's generation_config so later questions can match it."""
    return {
        "question": question,
        "key_tokens": key_tokens(question),
        "history_turns": history_turns,
    }


@dataclass(slots=True)
class Reuse:
    message: ChatMessage
    question: str
    similarity: float
    # Passage (chunk) ids in the order the earlier answer numbered them: [1], [2], …
    order: list[uuid.UUID]


def _same_writer(config: dict[str, Any], model: str, prompt_version: str, verifier: str) -> bool:
    return (
        config.get("llm_model") == model
        and config.get("prompt_version") == prompt_version
        and config.get("verifier") == verifier
    )


async def find_reusable(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    question: str,
    evidence: list[Evidence],
    model: str,
    prompt_version: str,
) -> Reuse | None:
    if not settings.answer_cache_enabled or not evidence:
        return None
    since = datetime.now(UTC) - timedelta(days=settings.answer_cache_days)
    wanted_passages = {e.result.chunk.id for e in evidence}
    candidates = list(
        (
            await session.execute(
                select(ChatMessage)
                .join(Citation, Citation.message_id == ChatMessage.id)
                .where(
                    ChatMessage.user_id == user_id,
                    ChatMessage.role == "assistant",
                    ChatMessage.status == MessageStatus.COMPLETE,
                    ChatMessage.created_at >= since,
                    Citation.number == 1,
                    Citation.chunk_id.in_(wanted_passages),
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(50)
            )
        ).scalars()
    )
    matches = []
    for message in candidates:
        config = message.generation_config or {}
        cached = config.get("answer_cache") or {}
        if cached.get("history_turns") != 0 or not same_key_tokens(question, cached["question"]):
            continue
        if not _same_writer(config, model, prompt_version, settings.verifier_provider):
            continue
        if (message.support or {}).get("status") not in REUSABLE:
            continue  # never spread an answer that failed its own check
        matches.append((message, cached["question"]))
    if not matches:
        return None
    passages = await session.execute(
        select(Citation.message_id, Citation.number, Citation.chunk_id)
        .where(Citation.message_id.in_([m.id for m, _ in matches]))
        .order_by(Citation.message_id, Citation.number)
    )
    used: dict[uuid.UUID, list[uuid.UUID]] = {}
    for message_id, _, chunk_id in passages.all():
        if chunk_id is not None:  # a passage deleted since: that answer can't match
            used.setdefault(message_id, []).append(chunk_id)
    matches = [
        (m, q)
        for m, q in matches
        if len(used.get(m.id, [])) == len(wanted_passages) and set(used[m.id]) == wanted_passages
    ]
    if not matches:
        return None
    provider = get_embedding_provider(settings)
    asked = await asyncio.to_thread(embed_query, provider, question)
    best: tuple[tuple[int, float], Reuse] | None = None
    for message, earlier in matches:
        vector = await asyncio.to_thread(embed_query, provider, earlier)
        similarity = float(
            np.dot(asked, vector) / ((np.linalg.norm(asked) * np.linalg.norm(vector)) or 1.0)
        )
        if similarity < settings.answer_cache_min_similarity:
            continue
        # Better-checked answers first, then the closer question (ties: the newest, listed first).
        rank = (REUSABLE[(message.support or {})["status"]], similarity)
        if best is None or rank > best[0]:
            best = (rank, Reuse(message, earlier, round(similarity, 4), used[message.id]))
    return best[1] if best else None
