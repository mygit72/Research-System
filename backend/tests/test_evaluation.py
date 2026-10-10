"""Evaluation API: datasets, expected evidence, generated questions, retrieval and RAG runs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_indexing_api import upload

API = "/api/v1"


async def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture
async def library(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    ids = {}
    for key, paper in (("retrieval", sp.RETRIEVAL_PAPER), ("lora", sp.LORA_PAPER)):
        data = sp.write_sample_pdf(paper, tmp_path / f"{key}.pdf").read_bytes()
        ids[key] = await upload(auth_client, settings, f"{key}.pdf", data)
    return ids


async def passage(client: AsyncClient, query: str, paper: str) -> dict[str, Any]:
    found = await ok(await client.post(f"{API}/search", json={"query": query, "mode": "keyword"}))
    return next(r for r in found["results"] if r["document"]["id"] == paper)


async def run(client: AsyncClient, settings: Settings, dataset: str, body: dict[str, Any]) -> Any:
    created = await ok(
        await client.post(f"{API}/evaluation/datasets/{dataset}/runs", json=body), 202
    )
    await get_dispatcher(settings).drain()
    return await ok(await client.get(f"{API}/evaluation/runs/{created['id']}"))


async def test_retrieval_runs_compare_configurations(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    dataset = await ok(
        await auth_client.post(f"{API}/evaluation/datasets", json={"name": "Smoke test"}), 201
    )
    did = dataset["id"]
    rrf = await passage(
        auth_client, "reciprocal rank fusion of BM25 and dense rankings", library["retrieval"]
    )
    lora = await passage(
        auth_client, "rank-8 adapters within one point of full fine-tuning", library["lora"]
    )
    for question, hit in (
        ("How are the sparse and dense rankings combined?", rrf),
        ("How close do rank-8 adapters get to full fine-tuning?", lora),
    ):
        item = await ok(
            await auth_client.post(
                f"{API}/evaluation/datasets/{did}/items",
                json={"question": question, "chunk_ids": [hit["chunk_id"]]},
            ),
            201,
        )
        assert item["status"] == "verified" and item["source"] == "manual"
        expected = item["expected"][0]
        assert expected["document_id"] == hit["document"]["id"] and expected["quote"]

    hybrid = await run(auth_client, settings, did, {"name": "hybrid", "config": {"mode": "hybrid"}})
    bm25 = await run(
        auth_client, settings, did, {"name": "bm25", "config": {"mode": "keyword", "rrf_k": 30}}
    )
    for result in (hybrid, bm25):
        assert result["status"] == "ready", result["error_message"]
        assert result["items_evaluated"] == 2
        metrics = result["metrics"]
        assert 0 <= metrics["recall@10"] <= 1 and 0 <= metrics["ndcg@10"] <= 1
        assert metrics["recall@10"] > 0 and metrics["mrr"] > 0
        assert metrics["latency_search_p50_ms"] is not None and metrics["cost_usd"] == 0
        assert len(result["per_item"]) == 2 and result["per_item"][0]["top"]
    assert bm25["config"]["mode"] == "keyword" and bm25["config"]["rrf_k"] == 30
    assert bm25["config"]["index"]["papers"] == 2
    assert bm25["config"]["index"]["embedding_models"]

    runs = await ok(await auth_client.get(f"{API}/evaluation/runs", params={"dataset_id": did}))
    assert [r["name"] for r in runs] == ["bm25", "hybrid"]
    listed = await ok(await auth_client.get(f"{API}/evaluation/datasets"))
    assert listed[0]["verified"] == 2 and listed[0]["runs"] == 2


async def test_rag_run_scores_answers(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    dataset = await ok(
        await auth_client.post(f"{API}/evaluation/datasets", json={"name": "RAG"}), 201
    )
    did = dataset["id"]
    hit = await passage(
        auth_client, "rank-8 adapters within one point of full fine-tuning", library["lora"]
    )
    await ok(
        await auth_client.post(
            f"{API}/evaluation/datasets/{did}/items",
            json={
                "question": "How close do rank-8 adapters get to full fine-tuning?",
                "chunk_ids": [hit["chunk_id"]],
            },
        ),
        201,
    )
    result = await run(auth_client, settings, did, {"kind": "rag", "config": {"mode": "hybrid"}})
    assert result["status"] == "ready", result["error_message"]
    metrics = result["metrics"]
    for key in (
        "faithfulness",
        "citation_correctness",
        "context_recall",
        "context_precision",
        "answer_relevance",
    ):
        assert 0 <= metrics[key] <= 1, key
    assert metrics["context_recall"] == 1.0  # the expected passage reached the model
    assert metrics["tokens_input"] > 0 and metrics["insufficient"] == 0
    item = result["per_item"][0]
    assert item["answer"] and set(item["latency_ms"]) == {"search", "generate", "verify"}
    assert result["config"]["llm_model"] and result["config"]["verifier"]


async def test_generated_questions_need_review(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    dataset = await ok(
        await auth_client.post(f"{API}/evaluation/datasets", json={"name": "Gen"}), 201
    )
    did = dataset["id"]
    started = await ok(
        await auth_client.post(f"{API}/evaluation/datasets/{did}/generate", json={"count": 4}), 202
    )
    assert started["generation"]["status"] == "running"
    await get_dispatcher(settings).drain()
    dataset = await ok(await auth_client.get(f"{API}/evaluation/datasets/{did}"))
    assert dataset["generation"]["status"] == "done" and dataset["unverified"] == 4
    items = await ok(await auth_client.get(f"{API}/evaluation/datasets/{did}/items"))
    assert all(i["source"] == "generated" and i["status"] == "unverified" for i in items)
    assert {i["expected"][0]["document_id"] for i in items} == set(library.values())  # spread
    assert all(i["question"].endswith("?") for i in items)
    # Unchecked questions don't count.
    response = await auth_client.post(f"{API}/evaluation/datasets/{did}/runs", json={})
    assert (
        response.status_code == 422
        and "no verified questions" in response.json()["error"]["message"]
    )
    accepted = await ok(
        await auth_client.patch(
            f"{API}/evaluation/items/{items[0]['id']}", json={"status": "verified"}
        )
    )
    assert accepted["status"] == "verified"
    result = await run(auth_client, settings, did, {})
    assert result["items_evaluated"] == 1
    # A generated question's own passage is the expected evidence: it should be found.
    assert result["metrics"]["recall@10"] == 1.0


async def test_privacy_and_deletion(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    dataset = await ok(
        await auth_client.post(f"{API}/evaluation/datasets", json={"name": "Mine"}), 201
    )
    hit = await passage(auth_client, "rank-8 adapters", library["lora"])
    owner = auth_client.headers["Authorization"]
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    await ok(await client.get(f"{API}/evaluation/datasets/{dataset['id']}"), 404)
    assert await ok(await client.get(f"{API}/evaluation/datasets")) == []
    own = await ok(await client.post(f"{API}/evaluation/datasets", json={"name": "Theirs"}), 201)
    await ok(  # someone else's passage can't be expected evidence
        await client.post(
            f"{API}/evaluation/datasets/{own['id']}/items",
            json={"question": "What is this about?", "chunk_ids": [hit["chunk_id"]]},
        ),
        422,
    )
    client.headers["Authorization"] = owner
    await ok(await client.delete(f"{API}/evaluation/datasets/{dataset['id']}"), 204)
    await ok(await client.get(f"{API}/evaluation/datasets/{dataset['id']}"), 404)
