"""Literature reviews, research gaps, disagreements and deep research (report API)."""

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
    for key, paper in (
        ("retrieval", sp.RETRIEVAL_PAPER),
        ("lora", sp.LORA_PAPER),
        ("rala", sp.RAG_ADAPTER_PAPER),
    ):
        data = sp.write_sample_pdf(paper, tmp_path / f"{key}.pdf").read_bytes()
        ids[key] = await upload(auth_client, settings, f"{key}.pdf", data)
    return ids


async def run(client: AsyncClient, settings: Settings, path: str, body: dict[str, Any]) -> Any:
    created = await ok(await client.post(f"{API}{path}", json=body), 202)
    assert created["status"] == "queued"
    await get_dispatcher(settings).drain()
    return await ok(await client.get(f"{API}/reports/{created['id']}"))


def section(report: dict[str, Any], key: str) -> dict[str, Any]:
    return next(s for s in report["sections"] if s["key"] == key)


async def test_literature_review_is_structured_cited_and_checked(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    report = await run(
        auth_client, settings, "/literature-review", {"document_ids": list(library.values())}
    )
    assert report["status"] == "ready", report["error_message"]
    assert report["kind"] == "review" and report["title"] == "Literature review of 3 papers"
    assert set(report["document_ids"]) == set(library.values())
    keys = [s["key"] for s in report["sections"]]
    assert keys[0] == "overview" and "chronology" in keys and "comparison" in keys
    assert keys[-1] == "gaps"
    # Three papers form one theme; every written section cites passages it was given.
    themes = [s for s in report["sections"] if s["key"].startswith("theme-")]
    assert len(themes) == 1 and len(themes[0]["data"]["papers"]) == 3
    numbers = {s["number"] for s in report["sources"]}
    for written in [section(report, "overview"), *themes]:
        assert written["origin"] == "generated" and written["text"]
        assert set(written["citations"]) <= numbers
        assert written["claims"] and all(c["status"] for c in written["claims"])
    assert report["support"]["statements"] > 0
    # Chronology and comparison come from metadata and entities, in year order.
    years = [r["year"] for r in section(report, "chronology")["data"]["rows"]]
    assert years == sorted(years) == [2023, 2024, 2024]
    rows = section(report, "comparison")["data"]["rows"]
    rala = next(r for r in rows if r["document"]["id"] == library["rala"])
    assert "SciQA-2400" in rala["datasets"]
    # Gaps: the authors' own limitations, labelled, citing passages; synthesis labelled too.
    gaps = section(report, "gaps")["data"]
    stated = [g for g in gaps["gaps"] if g["origin"] == "Stated by the authors"]
    assert stated and all(s["citations"] for g in stated for s in g["statements"])
    assert {g["origin"] for g in gaps["gaps"]} <= {
        "Stated by the authors",
        "System-generated synthesis",
    }
    for direction in gaps["directions"]:
        assert direction["based_on"] and direction["origin"] == "System-generated synthesis"
    # Missing summaries were written for the review, and reused the next time.
    assert len(report["trace"]["summaries_written"]) == 3
    again = await run(
        auth_client, settings, "/literature-review", {"document_ids": list(library.values())}
    )
    assert again["trace"]["summaries_written"] == []


async def test_review_from_a_topic_finds_the_papers(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    report = await run(
        auth_client,
        settings,
        "/literature-review",
        {"topic": "low-rank adapters", "depth": "brief"},
    )
    assert report["status"] == "ready", report["error_message"]
    assert report["title"] == "low-rank adapters"
    assert library["lora"] in report["document_ids"]
    assert report["trace"]["papers"]["how"] == "search"


async def test_gaps_for_a_collection_and_disagreements(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    collection = await ok(
        await auth_client.post(
            f"{API}/collections",
            json={"name": "Thesis", "document_ids": list(library.values())},
        ),
        201,
    )
    gaps = await run(auth_client, settings, "/research-gaps", {"collection_id": collection["id"]})
    assert gaps["status"] == "ready", gaps["error_message"]
    assert gaps["title"] == "Research gaps: “Thesis”"
    assert [s["key"] for s in gaps["sections"]] == ["gaps"]
    items = gaps["sections"][0]["data"]["gaps"]
    assert any(g["kind"] == "stated" for g in items)
    assert all(g["papers"] for g in items)

    disagreements = await run(
        auth_client,
        settings,
        "/contradictions",
        {"document_ids": [library["retrieval"], library["rala"]]},
    )
    assert disagreements["status"] == "ready", disagreements["error_message"]
    assert disagreements["sections"][0]["kind"] == "disagreements"
    assert "not a judgement" in disagreements["sections"][0]["label"]


async def test_deep_research_is_bounded_and_traced(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    report = await run(
        auth_client,
        settings,
        "/deep-research",
        {"question": "How does reciprocal rank fusion combine BM25 and dense retrieval?"},
    )
    assert report["status"] == "ready", report["error_message"]
    trace = report["trace"]
    actions = [s["action"] for s in trace["steps"]]
    assert actions[0] == "plan" and "search" in actions and "answer" in actions
    assert trace["tools"] == ["search_papers: hybrid search over your papers (read-only)"]
    assert trace["used"]["steps"] <= trace["limits"]["max_steps"]
    answers = [s for s in report["sections"] if s["kind"] == "answer"]
    assert answers and answers[0]["citations"]
    assert report["sources"] and library["retrieval"] in report["document_ids"]

    limited = await run(
        auth_client,
        settings,
        "/deep-research",
        {"question": "What do these papers say about rank fusion?", "max_steps": 3},
    )
    assert limited["status"] == "ready"
    assert limited["trace"]["limits"]["max_steps"] == 3
    assert limited["trace"]["used"]["steps"] <= 3  # stopping itself: test_analysis_unit


async def test_editing_and_exporting(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    report = await run(
        auth_client, settings, "/literature-review", {"document_ids": list(library.values())}
    )
    edited = await ok(
        await auth_client.patch(
            f"{API}/reports/{report['id']}",
            json={
                "title": "My review",
                "sections": [{"key": "overview", "text": "My own introduction [1]."}],
            },
        )
    )
    overview = section(edited, "overview")
    assert edited["title"] == "My review" and edited["edited_at"]
    assert overview["text"] == "My own introduction [1]." and overview["edited"] is True
    assert overview["label"] == "Edited by you — not re-checked"
    await ok(
        await auth_client.patch(
            f"{API}/reports/{report['id']}",
            json={"sections": [{"key": "comparison", "text": "x"}]},
        ),
        422,
    )

    md = await auth_client.get(f"{API}/reports/{report['id']}/export", params={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    text = md.text
    assert text.startswith("# My review") and "My own introduction [1]." in text
    assert "## Sources" in text and "Stated by the authors" in text
    assert 'filename="my-review.md"' in md.headers["content-disposition"]
    docx = await auth_client.get(f"{API}/reports/{report['id']}/export", params={"format": "docx"})
    assert docx.status_code == 200 and docx.content[:2] == b"PK"
    pdf = await auth_client.get(f"{API}/reports/{report['id']}/export", params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    listed = await ok(await auth_client.get(f"{API}/reports", params={"kind": "review"}))
    assert listed[0]["id"] == report["id"]
    await ok(await auth_client.delete(f"{API}/reports/{report['id']}"), 204)
    await ok(await auth_client.get(f"{API}/reports/{report['id']}"), 404)


async def test_validation_failures_and_privacy(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    await ok(await auth_client.post(f"{API}/literature-review", json={}), 422)
    await ok(await auth_client.post(f"{API}/deep-research", json={"question": "Why?"}), 422)
    await ok(
        await auth_client.post(f"{API}/contradictions", json={"document_ids": [library["lora"]]}),
        422,
    )
    # A topic nothing in the library is about: the job fails with an explanation.
    failed = await run(
        auth_client, settings, "/literature-review", {"topic": "quantum chromodynamics lattice"}
    )
    assert failed["status"] == "failed" and "this needs at least 2" in failed["error_message"]

    report = await run(auth_client, settings, "/research-gaps", {"document_ids": [library["lora"]]})
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    await ok(await client.get(f"{API}/reports/{report['id']}"), 404)
    assert await ok(await client.get(f"{API}/reports")) == []
    await ok(
        await client.post(
            f"{API}/literature-review", json={"document_ids": list(library.values())}
        ),
        404,
    )
