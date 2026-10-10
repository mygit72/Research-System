"""Rank fusion: combine ranked lists from different retrievers into one.

Reciprocal Rank Fusion (Cormack et al., 2009):

    RRF(d) = Σ_{r ∈ retrievers}  1 / (k + rank_r(d))        (rank starts at 1)

Only ranks are used, never raw scores, so BM25 scores (unbounded) and cosine
similarities (−1…1) never need calibrating against each other. A document found
by both retrievers gets two contributions, which is why hybrid search rewards
agreement. `k` damps the advantage of the very top ranks (60 in the paper).

Fusion is behind `FusionMethod` so weighted RRF or CombSUM can be added and
compared in the evaluation framework later.
"""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class Contribution:
    rank: int
    score: float  # the retriever's own score (shown in explanations, not used by RRF)
    contribution: float  # what this retriever added to the fused score


@dataclass(slots=True)
class FusedHit:
    key: Hashable
    score: float
    contributions: dict[str, Contribution] = field(default_factory=dict)

    @property
    def best_rank(self) -> int:
        return min(c.rank for c in self.contributions.values())


# A ranked list: (key, retriever score), best first.
Ranking = list[tuple[Hashable, float]]


class FusionMethod(Protocol):
    name: str

    def fuse(self, rankings: dict[str, Ranking], limit: int) -> list[FusedHit]: ...


@dataclass(frozen=True)
class ReciprocalRankFusion:
    k: int = 60
    name: str = "rrf"

    def fuse(self, rankings: dict[str, Ranking], limit: int) -> list[FusedHit]:
        if self.k < 0:
            raise ValueError("RRF k must be non-negative")
        fused: dict[Hashable, FusedHit] = {}
        for retriever, ranking in rankings.items():
            for rank, (key, score) in enumerate(ranking, start=1):
                contribution = 1.0 / (self.k + rank)
                hit = fused.setdefault(key, FusedHit(key, 0.0))
                hit.score += contribution
                hit.contributions[retriever] = Contribution(rank, score, contribution)
        # Ties (common: rank 1 in BM25 vs rank 1 in dense) → better best rank, then more
        # retrievers agreeing, then a stable key order, so results never shuffle between calls.
        ordered = sorted(
            fused.values(),
            key=lambda h: (-h.score, h.best_rank, -len(h.contributions), str(h.key)),
        )
        return ordered[:limit]
