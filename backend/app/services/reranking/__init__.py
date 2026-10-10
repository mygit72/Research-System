"""Rerankers, selected by configuration (RERANKER_PROVIDER / RERANKER_MODEL), plus a score cache.

Pipeline position: retrieve a large candidate set (cheap, high recall) → fuse →
rerank the top `RERANK_CANDIDATES` with a cross-encoder (expensive, precise).
"""

from __future__ import annotations

import struct
from functools import lru_cache

from app.core.cache import NamedCache, digest
from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.services.models.manager import model_manager
from app.services.reranking.base import RerankerProvider, RerankError, sigmoid
from app.services.reranking.lexical import LexicalReranker
from app.services.reranking.local import CrossEncoderReranker
from app.services.reranking.remote import ApiReranker


@lru_cache(maxsize=8)
def _build(
    provider: str,
    model: str,
    device: str,
    dtype: str,
    batch_size: int,
    max_length: int,
    api_key: str,
    base_url: str,
    local_only: bool,
) -> RerankerProvider | None:
    if provider == "none":
        return None
    if provider == "lexical":
        return LexicalReranker()
    if provider == "cross_encoder":
        return CrossEncoderReranker(
            model, model_manager, device=device, dtype=dtype,
            batch_size=batch_size, max_length=max_length,
        )  # fmt: skip
    if provider == "api":
        if local_only:
            raise ServiceUnavailableError(
                "Remote rerankers are disabled (LOCAL_ONLY=true).",
                hint="Use a local cross-encoder or turn off local-only mode.",
            )
        if not api_key:
            raise ServiceUnavailableError("RERANKER_API_KEY is not configured.")
        return ApiReranker(model, api_key, base_url)
    raise ServiceUnavailableError(f"Unknown reranker provider “{provider}”.")


def get_reranker(settings: Settings) -> RerankerProvider | None:
    """The configured reranker, or None when reranking is turned off."""
    return _build(
        settings.reranker_provider,
        settings.reranker_model,
        settings.model_device,
        settings.model_dtype,
        settings.reranker_batch_size,
        settings.reranker_max_length,
        settings.reranker_api_key.get_secret_value() if settings.reranker_api_key else "",
        settings.reranker_api_base,
        settings.local_only,
    )


class ScoreCache:
    """(model, query, passage) → score. People refine and repeat searches; passages recur.

    Backed by the two-tier cache (process LRU, plus Redis when configured).
    """

    def __init__(self, max_entries: int = 50_000) -> None:
        self.max_entries = max_entries
        self._cache: NamedCache[float] = NamedCache(
            "rerank_scores",
            max_entries,
            encode=lambda v: struct.pack("<d", v),
            decode=lambda b: struct.unpack("<d", b)[0],
        )

    def score(
        self, reranker: RerankerProvider, query: str, passages: list[str]
    ) -> tuple[list[float], int]:
        """Scores for every passage, computing only the uncached ones. Returns (scores, cached)."""
        keys = [digest(reranker.model_id, query, p) for p in passages]
        scores = self._cache.get_many(keys)
        missing = [i for i, s in enumerate(scores) if s is None]
        if missing:
            computed = reranker.score(query, [passages[i] for i in missing])
            fresh = {}
            for i, value in zip(missing, computed, strict=True):
                scores[i] = fresh[keys[i]] = float(value)
            self._cache.set_many(fresh)
        return [float(s) for s in scores if s is not None], len(passages) - len(missing)

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()


score_cache = ScoreCache()

__all__ = [
    "ApiReranker",
    "CrossEncoderReranker",
    "LexicalReranker",
    "RerankError",
    "RerankerProvider",
    "ScoreCache",
    "get_reranker",
    "score_cache",
    "sigmoid",
]
