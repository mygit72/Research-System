from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.projects.paper_run_match import assess_paper_run_match
from tests.test_indexing_api import upload

API = "/api/v1"


def test_assesses_numeric_delta_only_after_protocol_alignment() -> None:
    exact = assess_paper_run_match(
        paper_dataset="SQuAD", paper_system="BM25", paper_metric="Exact Match",
        paper_split="validation", run_dataset="squad", run_system="bm25",
        run_metric="exact match", run_split="Validation", reported_mean=0.8,
        reproduced_mean=0.81, tolerance=0.02,
    )
    assert exact["status"] == "within_tolerance"
    assert exact["alignment"] == "exact"
    assert exact["difference"] == 0.01

    mismatch = assess_paper_run_match(
        paper_dataset="SQuAD", paper_system="BM25", paper_metric="Exact Match",
        paper_split="test", run_dataset="SQuAD", run_system="BM25",
        run_metric="Exact Match", run_split="validation", reported_mean=0.8,
        reproduced_mean=0.8, tolerance=0.02,
    )
    assert mismatch["status"] == "not_comparable"
    assert mismatch["split_matches"] is False

    mapped = assess_paper_run_match(
        paper_dataset="SQuAD 1.1", paper_system="Lexical baseline", paper_metric="EM",
        paper_split="validation", run_dataset="SQuAD", run_system="BM25",
        run_metric="Exact Match", run_split="validation", reported_mean=0.8,
        reproduced_mean=0.85, tolerance=0.02, map_labels=True,
        mapping_note="The paper names its BM25 baseline by implementation type.",
    )
    assert mapped["status"] == "diverged"
    assert mapped["alignment"] == "user_mapped"
    assert {item["field"] for item in mapped["label_mismatches"]} == {"dataset", "system", "metric"}


async def test_paper_run_match_saves_verified_paper_evidence_and_run_snapshot(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    pdf = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "retrieval.pdf").read_bytes()
    document_id = await upload(auth_client, settings, "retrieval.pdf", pdf)
    collection = await auth_client.post(
        f"{API}/collections", json={"name": "Paper result source", "document_ids": [document_id]}
    )
    assert collection.status_code == 201, collection.text
    created = await auth_client.post(
        f"{API}/projects",
        json={"idea": "Reproduce a reported retrieval baseline.", "collection_id": collection.json()["id"]},
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]

    csv_text = (
        "experiment,dataset,system,seed,metric,value,status,note\n"
        "main,toy,BM25,1,Exact match,0.79,ok,\n"
        "main,toy,BM25,2,Exact match,0.80,ok,\n"
        "main,toy,BM25,3,Exact match,0.81,ok,\n"
    )
    imported = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/analyze-results",
        json={"filename": "results.csv", "csv_text": csv_text},
    )
    assert imported.status_code == 200, imported.text
    analysis = imported.json()["steps"]["experiments"]["result_analyses"][0]

    chunks_response = await auth_client.get(f"{API}/documents/{document_id}/chunks?limit=100")
    assert chunks_response.status_code == 200, chunks_response.text
    chunk = next(item for item in chunks_response.json()["items"] if item["kind"] == "table")

    body = {
        "result_analysis_id": analysis["id"],
        "run_experiment": "main",
        "run_dataset": "toy",
        "run_system": "BM25",
        "run_metric": "Exact match",
        "run_split": "validation",
        "evidence_chunk_id": chunk["id"],
        "paper_dataset": "toy",
        "paper_system": "BM25",
        "paper_metric": "Exact match",
        "paper_split": "validation",
        "reported_mean": 0.80,
        "reported_std": 0.01,
        "tolerance": 0.02,
    }
    response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/paper-run-matches", json=body
    )
    assert response.status_code == 200, response.text
    saved = response.json()["steps"]["experiments"]["paper_run_matches"][0]
    assert saved["status"] == "within_tolerance"
    assert saved["run"]["mean"] == 0.8
    assert saved["run"]["seed_count"] == 3
    assert saved["paper"]["document_id"] == document_id
    assert saved["paper"]["chunk_id"] == chunk["id"]
    assert saved["paper"]["quote"] == chunk["text"][:1800]

    not_comparable = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/paper-run-matches",
        json={**body, "paper_split": "test"},
    )
    assert not_comparable.status_code == 200, not_comparable.text
    assert not_comparable.json()["steps"]["experiments"]["paper_run_matches"][0]["status"] == "not_comparable"

    invalid_source = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/paper-run-matches",
        json={**body, "evidence_chunk_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert invalid_source.status_code == 422

    match_id = saved["id"]
    deleted = await auth_client.delete(
        f"{API}/projects/{project_id}/experiments/paper-run-matches/{match_id}"
    )
    assert deleted.status_code == 200, deleted.text
    assert all(
        item["id"] != match_id
        for item in deleted.json()["steps"]["experiments"]["paper_run_matches"]
    )
