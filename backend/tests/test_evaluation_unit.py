"""Retrieval metrics on worked examples (computed by hand in the comments)."""

from __future__ import annotations

import math

import pytest

from app.services.evaluation.metrics import (
    Passage,
    Span,
    covers,
    mean,
    ndcg_at_k,
    paper_recall_at_k,
    percentile,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    retrieval_metrics,
)
from app.services.evaluation.service import parse_question, prose_ratio

S1 = Span("A", "a1", 0, 100, "LoRA freezes the pretrained weights")
S2 = Span("B", "b1", 500, 600, "Hybrid retrieval fuses rankings")
P1 = Passage("A", "a1", 50, 150)  # covers S1
P2 = Passage("C", "c1", 0, 100)  # irrelevant
P3 = Passage("A", "a1", 60, 90)  # covers S1 again (a duplicate hit)
P4 = Passage("B", "b1", 550, 650)  # covers S2
RANKING = [P1, P2, P3, P4]


def test_recall_precision_mrr() -> None:
    assert recall_at_k(RANKING, [S1, S2], 1) == 0.5
    assert recall_at_k(RANKING, [S1, S2], 4) == 1.0
    assert precision_at_k(RANKING, [S1, S2], 2) == 0.5
    assert precision_at_k(RANKING, [S1, S2], 4) == 0.75  # P1, P3, P4 relevant
    assert precision_at_k(RANKING[:2], [S1, S2], 10) == 0.1  # fewer than K returned
    assert reciprocal_rank(RANKING, [S1, S2]) == 1.0
    assert reciprocal_rank([P2, P4], [S1, S2]) == 0.5
    assert reciprocal_rank([P2], [S1, S2]) == 0.0
    assert paper_recall_at_k(RANKING, [S1, S2], 2) == 0.5


def test_ndcg_counts_a_span_once() -> None:
    # DCG = 1/log2(2) [P1, new span S1] + 0 [P2] + 0 [P3 covers S1 again] + 1/log2(5) [P4]
    dcg = 1.0 + 1.0 / math.log2(5)
    idcg = 1.0 + 1.0 / math.log2(3)  # two spans: ranks 1 and 2 ideally
    assert ndcg_at_k(RANKING, [S1, S2], 4) == pytest.approx(dcg / idcg)
    assert ndcg_at_k([P1, P4], [S1, S2], 2) == pytest.approx(1.0)
    assert ndcg_at_k([P2], [S1], 1) == 0.0


def test_relevance_survives_reprocessing_by_quote() -> None:
    reprocessed = Passage(
        "A", "a2", 0, 400, "Intro. LoRA freezes the pretrained weights and adds …"
    )
    other = Passage("A", "a2", 0, 400, "Something else entirely.")
    assert covers(reprocessed, S1) and not covers(other, S1)
    assert not covers(Passage("A", "a1", 100, 200), S1)  # touching ranges don't overlap


def test_aggregation_helpers() -> None:
    assert mean([{"mrr": 1.0, "x": None}, {"mrr": 0.5}]) == {"mrr": 0.75}
    assert percentile([10, 20, 30, 40], 0.5) == 20
    assert percentile([10, 20, 30, 40], 0.95) == 40
    assert percentile([], 0.5) is None
    metrics = retrieval_metrics(RANKING, [S1, S2], (1, 4))
    assert metrics["recall@4"] == 1.0 and metrics["ndcg@1"] == 1.0 and metrics["mrr"] == 1.0


def test_matches_scikit_learn_ndcg_without_duplicates() -> None:
    sklearn_metrics = pytest.importorskip("sklearn.metrics")
    import numpy as np

    # Distinct spans, no duplicate hits: our nDCG equals the standard binary nDCG.
    ranking = [P2, P1, P4]
    ours = ndcg_at_k(ranking, [S1, S2], 3)
    relevance = np.asarray([[0, 1, 1]])
    scores = np.asarray([[3, 2, 1]])
    assert ours == pytest.approx(sklearn_metrics.ndcg_score(relevance, scores, k=3))


def test_generated_question_parsing() -> None:
    assert parse_question("Question: Which datasets does RALA use for evaluation?") == (
        "Which datasets does RALA use for evaluation?"
    )
    assert parse_question('"How much memory does QLoRA save on a 65B model?"\nExplanation: …') == (
        "How much memory does QLoRA save on a 65B model?"
    )
    assert parse_question("LoRA is a method.") is None


def test_question_drafts_skip_figure_and_table_text() -> None:
    figure = "plain-20 plain-56 ResNet-20 ResNet-56 ResNet-110 3 2 1 0 20 40 60 80 100 layer index"
    table = "BERT (Ours) OpenAI GPT ... T1 T2 TN T1 T2 TN ... Trm Trm Trm E1 E2 EN"
    prose = (
        "We chose the sinusoidal version because it may allow the model to extrapolate to "
        "sequence lengths longer than the ones encountered during training."
    )
    assert prose_ratio(figure) < 0.5 and prose_ratio(table) < 0.5
    assert prose_ratio(prose) > 0.8
