"""Okapi BM25, implemented by hand so every number is inspectable.

    score(D, Q) = Σ_{t ∈ Q}  IDF(t) · tf(t, D) · (k1 + 1)
                            ─────────────────────────────────────────
                            tf(t, D) + k1 · (1 − b + b · |D| / avgdl)

    IDF(t) = ln(1 + (N − df(t) + 0.5) / (df(t) + 0.5))

- `k1` controls term-frequency saturation (0 = binary match; ~1.2 typical).
- `b` controls length normalization (0 = none; 1 = full).
- The IDF is the Lucene variant: always positive, so a term in more than half
  the passages still counts a little instead of *penalizing* a match.
- Repeated query terms count once (queries are short; repeats are usually noise).

Collection statistics (N, df, avgdl) always cover the user's whole library, and
filters restrict which passages may be *returned*. Filtering before the top-k
cut (not after) is what keeps filtered searches from losing recall.

The index is an inverted index (term → {passage → tf}) that supports adding and
removing passages, so a library is updated incrementally as papers change.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from collections.abc import Callable, Hashable
from dataclasses import dataclass, field


@dataclass(slots=True)
class BM25Hit:
    key: Hashable
    score: float
    matched_terms: dict[str, int]  # term → tf in this passage (for explanations)


@dataclass
class BM25Index:
    k1: float = 1.2
    b: float = 0.75
    postings: dict[str, dict[Hashable, int]] = field(default_factory=dict)
    lengths: dict[Hashable, int] = field(default_factory=dict)
    total_length: int = 0

    @property
    def size(self) -> int:
        return len(self.lengths)

    @property
    def avgdl(self) -> float:
        return self.total_length / self.size if self.size else 0.0

    def add(self, key: Hashable, terms: list[str]) -> None:
        if key in self.lengths:
            self.remove(key)
        for term, tf in Counter(terms).items():
            self.postings.setdefault(term, {})[key] = tf
        self.lengths[key] = len(terms)
        self.total_length += len(terms)

    def remove(self, key: Hashable, terms: list[str] | None = None) -> None:
        """Remove a passage. Pass its terms when known (fast); otherwise scans the vocabulary."""
        if key not in self.lengths:
            return
        vocabulary = set(terms) if terms is not None else list(self.postings)
        for term in vocabulary:
            posting = self.postings.get(term)
            if posting is not None and posting.pop(key, None) is not None and not posting:
                del self.postings[term]
        self.total_length -= self.lengths.pop(key)

    def idf(self, term: str) -> float:
        df = len(self.postings.get(term, ()))
        return math.log(1 + (self.size - df + 0.5) / (df + 0.5))

    def term_score(self, tf: int, length: int, idf: float) -> float:
        norm = self.k1 * (1 - self.b + self.b * length / (self.avgdl or 1.0))
        return idf * tf * (self.k1 + 1) / (tf + norm)

    def search(
        self,
        query_terms: list[str],
        limit: int,
        allow: Callable[[Hashable], bool] | None = None,
    ) -> list[BM25Hit]:
        """Top `limit` passages by BM25. `allow` filters candidates before ranking."""
        unique = list(dict.fromkeys(t for t in query_terms if t in self.postings))
        if not unique or limit <= 0:
            return []
        scores: dict[Hashable, float] = {}
        matched: dict[Hashable, dict[str, int]] = {}
        for term in unique:
            idf = self.idf(term)
            for key, tf in self.postings[term].items():
                if allow is not None and not allow(key):
                    continue
                scores[key] = scores.get(key, 0.0) + self.term_score(tf, self.lengths[key], idf)
                matched.setdefault(key, {})[term] = tf
        # Deterministic ties: higher score first, then the stable key order.
        best = heapq.nsmallest(limit, scores.items(), key=lambda item: (-item[1], str(item[0])))
        return [BM25Hit(key, score, matched[key]) for key, score in best]
