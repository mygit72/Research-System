"""Relevance scoring for Research Watches: anchor averaging and candidate ranking.

Uses the hashing embedding provider (fast, deterministic, no model download) — it captures
lexical overlap, not meaning, which is exactly what these tests check for.
"""

from __future__ import annotations

from app.core.config import Settings
from app.services.agent import relevance


def test_anchor_vector_is_just_the_topic_without_a_project(settings: Settings) -> None:
    anchor = relevance.anchor_vector(settings, "retrieval augmented generation", None)
    from app.services.embeddings import get_embedding_provider
    from app.services.retrieval.dense import embed_query

    direct = embed_query(get_embedding_provider(settings), "retrieval augmented generation")
    assert anchor.shape == direct.shape
    assert (anchor == direct).all()


def test_anchor_vector_averages_topic_and_project_question(settings: Settings) -> None:
    topic_only = relevance.anchor_vector(settings, "sparse retrieval", None)
    averaged = relevance.anchor_vector(settings, "sparse retrieval", "dense retrieval methods")
    # The averaged anchor is unit length and is not identical to either input alone.
    assert abs(float((averaged**2).sum()) - 1.0) < 1e-5
    assert not (averaged == topic_only).all()


def test_score_candidates_ranks_relevant_abstracts_higher(settings: Settings) -> None:
    anchor = relevance.anchor_vector(settings, "low rank adapters for fine-tuning", None)
    abstracts = [
        "We study low rank adapters for fine-tuning large language models.",
        "A survey of medieval European trade routes and currency systems.",
    ]
    scores = relevance.score_candidates(settings, anchor, abstracts)
    assert scores[0] > scores[1]


def test_score_candidates_handles_no_abstracts(settings: Settings) -> None:
    anchor = relevance.anchor_vector(settings, "anything", None)
    assert list(relevance.score_candidates(settings, anchor, [])) == []
