"""Checks that the evaluation machinery is right. Run: python -m pytest"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import metrics
import pytest

ROOT = Path(__file__).parent


def test_answer_metrics() -> None:
    assert metrics.exact_match("The Eiffel Tower!", ["eiffel tower"]) == 1.0
    assert metrics.exact_match("tower", ["eiffel tower"]) == 0.0
    assert metrics.accuracy(" Yes ", ["yes"]) == 1.0
    assert metrics.token_f1("eiffel tower paris", ["the eiffel tower"]) == pytest.approx(0.8)
    assert metrics.token_f1("nothing alike", ["eiffel tower"]) == 0.0


def test_retrieval_metrics_by_hand() -> None:
    ranking, relevant = [4, 2, 7, 1], [2, 1]
    assert metrics.recall_at_k(ranking, relevant, 2) == 0.5
    assert metrics.recall_at_k(ranking, relevant, 4) == 1.0
    assert metrics.precision_at_k(ranking, relevant, 2) == 0.5
    assert metrics.hit_at_k(ranking, relevant, 1) == 0.0
    assert metrics.hit_at_k(ranking, relevant, 2) == 1.0
    assert metrics.mrr(ranking, relevant) == 0.5
    assert metrics.mrr([9, 8], relevant) == 0.0
    dcg = 1 / math.log2(3) + 1 / math.log2(5)  # relevant at ranks 2 and 4
    ideal = 1 + 1 / math.log2(3)
    assert metrics.ndcg_at_k(ranking, relevant, 4) == pytest.approx(dcg / ideal)
    assert metrics.ndcg_at_k([2, 1], relevant, 2) == pytest.approx(1.0)


def test_metric_names_from_the_plan() -> None:
    assert [m.label for m in metrics.expand_metric("Recall@k")] == [
        "recall@1",
        "recall@5",
        "recall@10",
    ]
    assert [m.label for m in metrics.expand_metric("nDCG@10")] == ["ndcg@10"]
    assert [m.label for m in metrics.expand_metric("Top-k retrieval accuracy", (3,))] == ["hit@3"]
    assert [m.label for m in metrics.expand_metric("Exact match")] == ["exact_match"]
    with pytest.raises(metrics.UnknownMetric):
        metrics.expand_metric("Perplexity")


def test_smoke_run_works_and_beats_random() -> None:
    result = subprocess.run(
        [sys.executable, "run_experiments.py", "--smoke"],
        cwd=ROOT, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    rows = {}
    for line in result.stdout.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 5 and parts[3] == "recall@1":
            rows[parts[2]] = float(parts[4].split()[0])
    assert rows["Lexical overlap (sanity check)"] > rows["Random (sanity check)"]


def test_metrics_for_generated_answers() -> None:
    assert metrics.contains("It was the Eiffel Tower.", ["eiffel tower"]) == 1.0
    assert metrics.exact_match("It was the Eiffel Tower.", ["eiffel tower"]) == 0.0
    assert metrics.groundedness("Eiffel Tower", ["The Eiffel Tower is in Paris."]) == 1.0
    assert metrics.groundedness("Big Ben", ["The Eiffel Tower is in Paris."]) == 0.0
    assert metrics.abstention("Unanswerable.", ["x"]) == 1.0


def test_generation_without_a_model(tmp_path: Path) -> None:
    """The prompt, the cleaning and the cache, with a stand-in for the model call."""
    import generation

    assert generation.clean("Answer: Eiffel Tower [2]") == "Eiffel Tower"
    assert generation.clean("The passages do not mention it.") == generation.ABSTAIN
    assert generation.clean("No") == "No"  # an answer to a yes/no question, not an abstention
    system, user = generation.build_prompt("Where?", ["In Paris."])
    assert generation.ABSTAIN in system and "[1] In Paris." in user
    gen = generation.Generator("ollama", cache_path=tmp_path / "cache.jsonl")
    calls = []

    def stand_in(system: str, user: str, max_tokens: int) -> generation.Reply:
        calls.append(user)
        return generation.Reply("Paris")

    gen._call = stand_in  # type: ignore[method-assign]
    assert gen.answer("Where?", ["In Paris."]) == gen.answer("Where?", ["In Paris."]) == "Paris"
    assert len(calls) == 1  # the second answer came from the cache


def test_retrieval_rate() -> None:
    assert metrics.retrieval_rate([2, 0]) == 1.0 and metrics.retrieval_rate([]) == 0.0
    assert [m.label for m in metrics.expand_metric("Retrieval rate")] == ["retrieval_rate"]
