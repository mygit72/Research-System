"""Dependency-free reranker for tests and offline demos — NOT a real relevance model.

Scores query-term coverage (how many distinct analyzed query terms a passage
contains) with a small bonus for the terms appearing close together. Being
deterministic and fast lets tests check reranking behaviour without models.
"""

from __future__ import annotations


class LexicalReranker:
    is_remote = False
    model_id = "lexical-overlap-v1"

    def score(self, query: str, passages: list[str]) -> list[float]:
        # Imported here: the retrieval package imports reranking (avoids an import cycle).
        from app.services.retrieval.text import tokenize

        terms = {t.term for t in tokenize(query)}
        if not terms:
            return [0.0] * len(passages)
        scores = []
        for passage in passages:
            tokens = tokenize(passage)
            positions = [i for i, t in enumerate(tokens) if t.term in terms]
            found = {tokens[i].term for i in positions}
            coverage = len(found) / len(terms)
            span = (positions[-1] - positions[0] + 1) if positions else 0
            proximity = len(positions) / span if span else 0.0
            scores.append(round(0.9 * coverage + 0.1 * proximity, 6))
        return scores
