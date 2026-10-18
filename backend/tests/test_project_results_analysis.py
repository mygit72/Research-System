from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.projects.results_analysis import analyze_results_csv

API = "/api/v1"


CSV = """experiment,dataset,system,seed,metric,value,status,note
main-1,toy,baseline,1,Exact match,0.50,ok,
main-1,toy,proposed,1,Exact match,0.60,ok,
main-1,toy,baseline,2,Exact match,0.52,ok,
main-1,toy,proposed,2,Exact match,0.61,ok,
main-1,toy,baseline,3,Exact match,0.48,ok,
main-1,toy,proposed,3,Exact match,0.58,ok,
main-1,toy,proposed,4,Groundedness,,todo,Implement passage attribution
main-1,toy,baseline,4,-,,error,Model unavailable
"""


def test_analyzes_seed_summaries_paired_differences_and_incomplete_rows() -> None:
    result = analyze_results_csv(CSV)

    assert result["rows_seen"] == 8
    assert result["rows_analyzed"] == 6
    assert result["status_counts"] == {"error": 1, "ok": 6, "todo": 1}
    proposed = next(row for row in result["summaries"] if row["system"] == "proposed")
    assert proposed["seed_count"] == 3
    assert proposed["mean"] == 0.596667
    comparison = result["comparisons"][0]
    assert comparison["system_a"] == "baseline"
    assert comparison["system_b"] == "proposed"
    assert comparison["paired_seed_count"] == 3
    assert comparison["mean_difference"] == 0.096667
    assert comparison["ci95_lower"] < comparison["mean_difference"] < comparison["ci95_upper"]
    assert len(result["issues"]) == 2


def test_accepts_bom_and_averages_duplicate_values_within_a_seed() -> None:
    csv_text = "\ufeff" + """experiment,dataset,system,seed,metric,value,status,note
e,d,A,1,m,0.2,ok,
e,d,A,1,m,0.4,ok,
e,d,B,1,m,0.5,ok,
e,d,A,2,m,0.3,ok,
e,d,B,2,m,0.4,ok,
"""

    result = analyze_results_csv(csv_text)

    summary = result["summaries"][0]
    assert summary["seed_count"] == 2
    assert summary["mean"] == 0.3
    assert result["comparisons"][0]["mean_difference"] == 0.15


@pytest.mark.parametrize(
    ("csv_text", "message"),
    [
        ("experiment,dataset\ne,d\n", "Missing required results.csv columns"),
        (
            "experiment,dataset,system,seed,metric,value,status,note\ne,d,A,1,m,nan,ok,\n",
            "non-finite",
        ),
        (
            "experiment,dataset,system,seed,metric,value,status,note\ne,d,A,1,m,not-a-number,ok,\n",
            "not numeric",
        ),
        (
            "experiment,dataset,system,seed,metric,value,status,note\ne,d,A,1,m,0.1,ok,extra,unexpected\n",
            "expected 8",
        ),
    ],
)
def test_rejects_invalid_results_csv(csv_text: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        analyze_results_csv(csv_text)


def test_single_shared_seed_has_no_confidence_interval() -> None:
    result = analyze_results_csv(
        "experiment,dataset,system,seed,metric,value,status,note\n"
        "e,d,A,1,m,0.1,ok,\n"
        "e,d,B,1,m,0.2,ok,\n"
    )

    assert result["comparisons"][0]["paired_seed_count"] == 1
    assert result["comparisons"][0]["ci95_lower"] is None
    assert result["comparisons"][0]["ci95_upper"] is None


async def test_project_results_endpoint_saves_only_analysis_summary(auth_client: AsyncClient) -> None:
    project_response = await auth_client.post(
        f"{API}/projects", json={"idea": "Compare two research systems across random seeds."}
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]

    response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/analyze-results",
        json={"filename": "results.csv", "csv_text": CSV},
    )
    assert response.status_code == 200, response.text
    analysis = response.json()["steps"]["experiments"]["result_analyses"][0]
    assert analysis["filename"] == "results.csv"
    assert analysis["rows_analyzed"] == 6
    assert analysis["comparisons"][0]["paired_seed_count"] == 3
    assert "csv_text" not in analysis

    reread = await auth_client.get(f"{API}/projects/{project_id}")
    assert reread.status_code == 200, reread.text
    assert reread.json()["steps"]["experiments"]["result_analyses"][0]["id"] == analysis["id"]

    invalid = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/analyze-results",
        json={"csv_text": "experiment,dataset\ne,d\n"},
    )
    assert invalid.status_code == 422
