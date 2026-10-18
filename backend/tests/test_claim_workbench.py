from __future__ import annotations

import uuid
from dataclasses import replace
from pathlib import Path

from httpx import AsyncClient

from app.demo import sample_papers as sp
from app.core.config import Settings
from tests.test_indexing_api import upload

API = "/api/v1"
CLAIM = "Scaling attention scores by the square root of key dimension prevents softmax saturation."


async def test_claim_workbench_searches_project_papers_and_persists_a_reproducible_run(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    paper = replace(
        sp.RETRIEVAL_PAPER,
        title="Why Scaled Dot-Product Attention Works",
        abstract=(
            "We analyze the scale of dot-product attention logits and the softmax gradient "
            "as the key dimension grows."
        ),
        keywords=["attention", "softmax", "key dimension"],
        sections=[
            (
                "3 Scaled Dot-Product Attention",
                [
                    "For large values of d_k, the dot products grow large in magnitude, pushing "
                    "softmax into regions where its gradients are extremely small. We scale the "
                    "dot products by 1/sqrt(d_k) to counteract this effect.",
                ],
            ),
        ],
    )
    pdf = sp.write_sample_pdf(paper, tmp_path / "attention-scaling.pdf").read_bytes()
    document_id = await upload(auth_client, settings, "attention-scaling.pdf", pdf)
    collection_response = await auth_client.post(
        f"{API}/collections",
        json={"name": "Attention papers", "document_ids": [document_id]},
    )
    assert collection_response.status_code == 201, collection_response.text
    project_response = await auth_client.post(
        f"{API}/projects",
        json={
            "idea": "Understand how scaling changes attention at larger dimensions.",
            "collection_id": collection_response.json()["id"],
        },
    )
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    update = await auth_client.patch(
        f"{API}/projects/{project_id}",
        json={
            "question": "How does scaling affect attention as key dimension grows?",
            "hypothesis": "Scaling keeps softmax gradients useful at larger dimensions.",
        },
    )
    assert update.status_code == 200, update.text

    evidence_response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/claim-evidence",
        json={"claim": CLAIM},
    )
    assert evidence_response.status_code == 200, evidence_response.text
    evidence = evidence_response.json()
    assert evidence["status"] == "ok"
    assert evidence["paper_count"] == 1
    assert evidence["passages"][0]["title"] == paper.title
    assert "extremely small" in evidence["passages"][0]["quote"]

    run_response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/claim-run",
        json={
            "claim": CLAIM,
            "evidence_chunk_ids": [evidence["passages"][0]["chunk_id"]],
            "dimensions": [4, 64, 256],
            "seed": 42,
        },
    )
    assert run_response.status_code == 200, run_response.text
    saved = run_response.json()["steps"]["experiments"]["claim_runs"][0]
    assert saved["claim"] == CLAIM
    assert saved["question"] == "How does scaling affect attention as key dimension grows?"
    assert saved["hypothesis"] == "Scaling keeps softmax gradients useful at larger dimensions."
    assert saved["dimensions"] == [4, 64, 256]
    assert saved["seed"] == 42
    assert saved["evidence"][0]["chunk_id"] == evidence["passages"][0]["chunk_id"]
    assert saved["results"][-1]["unscaled"]["saturated_query_rate"] > saved["results"][-1]["paper_scaled"]["saturated_query_rate"]

    invalid_evidence = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/claim-run",
        json={
            "claim": CLAIM,
            "evidence_chunk_ids": [evidence["passages"][0]["chunk_id"], str(uuid.uuid4())],
            "dimensions": [4, 16],
            "seed": 42,
        },
    )
    assert invalid_evidence.status_code == 422

    reread = await auth_client.get(f"{API}/projects/{project_id}")
    assert reread.status_code == 200, reread.text
    assert reread.json()["steps"]["experiments"]["claim_runs"][0]["id"] == saved["id"]


async def test_claim_run_requires_a_project_paper_scope(
    auth_client: AsyncClient,
) -> None:
    project_response = await auth_client.post(
        f"{API}/projects", json={"idea": "Study a claim with project-specific papers."}
    )
    project_id = project_response.json()["id"]
    response = await auth_client.post(
        f"{API}/projects/{project_id}/experiments/claim-run",
        json={
            "claim": CLAIM,
            "evidence_chunk_ids": [str(uuid.uuid4())],
            "dimensions": [4, 16],
            "seed": 42,
        },
    )
    assert response.status_code == 409
