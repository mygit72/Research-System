from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

from app.services.projects.prediction_analysis import analyze_predictions_jsonl

API = "/api/v1"


def record(
    system: str,
    seed: int,
    score: float,
    *,
    question: str = "Which answer is supported?",
    example_id: str = "ex-1",
) -> dict:
    return {
        "experiment": "main-1",
        "dataset": "toy",
        "example_id": example_id,
        "system": system,
        "seed": seed,
        "question": question,
        "answer": f"{system} answer {seed}",
        "reference_answers": ["the correct answer"],
        "reference_passages": [{"index": 2, "text": "A source passage."}],
        "retrieved_passages": [{"index": 2, "relevant": True, "text": "Retrieved source."}],
        "used_passages": [{"index": 2, "text": "Passage used to answer."}],
        "metric_scores": {"exact_match": score, "contains": min(1.0, score + 0.1)},
    }


def jsonl(*rows: dict) -> str:
    return "\n".join(json.dumps(row) for row in rows)


def test_ranks_hard_cases_and_keeps_compact_answer_evidence_context() -> None:
    result = analyze_predictions_jsonl(
        jsonl(
            record("baseline", 1, 0.0),
            record("proposed", 1, 0.5),
            record("baseline", 2, 0.5),
            record("proposed", 2, 1.0),
            record("baseline", 1, 1.0, question="Easy one", example_id="ex-2"),
            record("proposed", 1, 1.0, question="Easy one", example_id="ex-2"),
        ),
        "exact_match",
    )

    assert result["records_seen"] == 6
    assert result["records_scored"] == 6
    assert result["metrics"] == ["contains", "exact_match"]
    assert result["cases"][0]["question"] == "Which answer is supported?"
    hard = result["cases"][0]
    assert hard["best_system_score"] == 0.75
    assert hard["score_spread"] == 0.5
    assert hard["reference_answers"] == ["the correct answer"]
    assert hard["systems"][0]["runs"][0]["used_passages"][0]["text"] == "Passage used to answer."
    assert "jsonl_text" not in result


def test_lower_is_better_reverses_hard_case_ranking() -> None:
    rows = [
        record("a", 1, 0.8, question="High error", example_id="high"),
        record("b", 1, 0.9, question="High error", example_id="high"),
        record("a", 1, 0.1, question="Low error", example_id="low"),
        record("b", 1, 0.2, question="Low error", example_id="low"),
    ]

    result = analyze_predictions_jsonl(jsonl(*rows), "exact_match", higher_is_better=False)

    assert result["higher_is_better"] is False
    assert result["cases"][0]["question"] == "High error"


@pytest.mark.parametrize(
    ("jsonl_text", "metric", "message"),
    [
        ("", "exact_match", "contains no prediction rows"),
        ('{"question":"q","system":"s"}', "exact_match", "no per-example metric scores"),
        (json.dumps({**record("a", 1, 0.2), "metric_scores": {"exact_match": 1.2}}), "exact_match", "outside the expected 0–1 range"),
        ("{bad json}", "exact_match", "not valid JSON"),
    ],
)
def test_rejects_invalid_or_unscored_prediction_exports(jsonl_text: str, metric: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        analyze_predictions_jsonl(jsonl_text, metric)


async def test_prediction_analysis_endpoint_saves_hard_cases_not_source_jsonl(auth_client: AsyncClient) -> None:
    project_response = await auth_client.post(
        f"{API}/projects", json={"idea": "Inspect where a research system fails on individual questions."}
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/analyze-predictions",
        json={
            "filename": "predictions_main-1.jsonl",
            "metric": "exact_match",
            "higher_is_better": True,
            "jsonl_text": jsonl(record("baseline", 1, 0), record("proposed", 1, 1)),
        },
    )
    assert response.status_code == 200, response.text
    saved = response.json()["steps"]["experiments"]["prediction_analyses"][0]
    assert saved["filename"] == "predictions_main-1.jsonl"
    assert saved["cases"][0]["systems"][1]["system"] == "proposed"
    assert "jsonl_text" not in saved

    invalid = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/analyze-predictions",
        json={"metric": "exact_match", "jsonl_text": "{bad json}"},
    )
    assert invalid.status_code == 422
