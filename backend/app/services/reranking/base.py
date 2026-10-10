from __future__ import annotations

import math
from typing import Protocol


class RerankError(Exception):
    """Reranking failed (model unavailable, remote error). `user_message` is safe to show."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class RerankerProvider(Protocol):
    """Scores (query, passage) pairs jointly — slower than a bi-encoder, but more precise.

    Scores are relevance estimates in [0, 1] (higher is better), so different
    rerankers can be shown and compared on one scale.
    """

    model_id: str
    is_remote: bool

    def score(self, query: str, passages: list[str]) -> list[float]: ...


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x)) if x >= 0 else math.exp(x) / (1.0 + math.exp(x))
