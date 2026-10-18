"""Standard BEIR/trec_eval retrieval metrics, computed from scratch (binary relevance).

Definitions match pytrec_eval / the official BEIR harness:
  - Recall@K    = |relevant docs in top K| / |relevant docs|
  - MRR@K       = 1 / rank of the first relevant doc in top K (0 if none)
  - nDCG@K      = DCG@K / IDCG@K, DCG@K = sum_i rel_i / log2(i + 1) (rank i starts at 1)
                  IDCG@K = best possible DCG@K given the number of relevant docs

A query is skipped if it has no relevance judgments (shouldn't happen on a
standard BEIR test split, where every query has >= 1 relevant doc).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def _dcg(gains: list[int], k: int) -> float:
    return sum(g / math.log2(i + 2) for i, g in enumerate(gains[:k]))


def recall_at_k(ranked_docs: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(ranked_docs[:k])
    return len(top & relevant) / len(relevant)


def mrr_at_k(ranked_docs: list[str], relevant: set[str], k: int) -> float:
    for i, doc in enumerate(ranked_docs[:k], start=1):
        if doc in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked_docs: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    gains = [1 if d in relevant else 0 for d in ranked_docs[:k]]
    dcg = _dcg(gains, k)
    ideal = [1] * min(len(relevant), k)
    idcg = _dcg(ideal, k)
    return dcg / idcg if idcg > 0 else 0.0


@dataclass(slots=True)
class QueryScore:
    qid: str
    ndcg10: float
    recall10: float
    recall100: float
    mrr10: float


def score_query(qid: str, ranked_docs: list[str], relevant: set[str]) -> QueryScore:
    return QueryScore(
        qid=qid,
        ndcg10=ndcg_at_k(ranked_docs, relevant, 10),
        recall10=recall_at_k(ranked_docs, relevant, 10),
        recall100=recall_at_k(ranked_docs, relevant, 100),
        mrr10=mrr_at_k(ranked_docs, relevant, 10),
    )


def aggregate(scores: list[QueryScore]) -> dict[str, float]:
    n = len(scores) or 1
    return {
        "nDCG@10": round(sum(s.ndcg10 for s in scores) / n, 4),
        "Recall@10": round(sum(s.recall10 for s in scores) / n, 4),
        "Recall@100": round(sum(s.recall100 for s in scores) / n, 4),
        "MRR@10": round(sum(s.mrr10 for s in scores) / n, 4),
        "n_queries": len(scores),
    }
