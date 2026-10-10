"""Paper comparisons: table, citations across papers, cache, overview, validation, API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.comparisons import ROWS, ComparisonKind, agreement
from app.services.comparisons.generate import _shift, short_title
from app.services.llm import FakeLLM, LLMError
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register
from tests.test_indexing_api import upload

# --- units ---------------------------------------------------------------------------------------


def cell(text: str, status: str = "supported") -> dict[str, Any]:
    return {"text": text, "status": status}


def test_agreement_between_cells() -> None:
    same = "Low-rank adapters reduce GPU memory [1]."
    assert (
        agreement([cell(same), cell("Low-rank adapters reduce the GPU memory [7].")]) == "similar"
    )
    assert (
        agreement([cell(same), cell("Hybrid retrieval fuses BM25 and dense [8].")]) == "different"
    )
    assert agreement([cell(same), cell("Not reported.", "not_reported")]) == "partial"
    assert agreement([cell("Not reported.", "not_reported")] * 2) == "none"


def test_cells_are_renumbered_into_the_comparison_sources() -> None:
    shifted = _shift(
        {
            "text": "Memory drops by 60 percent [2][3].",
            "citations": [2, 3],
            "claims": [
                {"text": "x", "citations": [2], "best_passage": 3, "found_in": None, "status": "s"}
            ],
        },
        offset=10,
    )
    assert shifted["text"] == "Memory drops by 60 percent [12][13]."
    assert shifted["citations"] == [12, 13]
    assert shifted["claims"][0]["citations"] == [12] and shifted["claims"][0]["best_passage"] == 13


def test_short_titles() -> None:
    assert short_title("LoRA: Low-Rank Adaptation of Large Language Models") == "LoRA"
    assert len(short_title("x" * 80)) == 48


# --- end to end ----------------------------------------------------------------------------------


@pytest.fixture
async def library(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    retrieval = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    lora = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    notes = sp.write_sample_markdown(sp.RETRIEVAL_PAPER, tmp_path / "n.md").read_bytes()
    return {
        "retrieval": await upload(auth_client, settings, "r.pdf", retrieval),
        "lora": await upload(auth_client, settings, "l.pdf", lora),
        "notes": await upload(auth_client, settings, "n.md", notes, "text/markdown"),
    }


async def compare(client: AsyncClient, settings: Settings, ids: list[str], **body: Any) -> Any:
    response = await client.post("/api/v1/comparisons", json={"document_ids": ids, **body})
    assert response.status_code == 202, response.text
    await get_dispatcher(settings).drain()
    result = (await client.get(f"/api/v1/comparisons/{response.json()['id']}")).json()
    return result


async def jobs_of(client: AsyncClient, kind: str) -> list[dict[str, Any]]:
    jobs = (await client.get("/api/v1/jobs?limit=100")).json()["items"]
    return [j for j in jobs if j["kind"] == kind]


async def test_two_papers_are_compared_with_cited_checked_cells(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    ids = [library["lora"], library["retrieval"]]
    result = await compare(auth_client, settings, ids)
    assert result["status"] == "ready", result["error_message"]
    assert [c["document_id"] for c in result["columns"]] == ids  # the user's order
    assert [c["letter"] for c in result["columns"]] == ["A", "B"]
    assert result["title"].startswith("Low-Rank Adapters") and " vs " in result["title"]
    assert [r["key"] for r in result["rows"]] == [f.key for f in ROWS[ComparisonKind.PAPERS]]

    sources = {s["number"]: s for s in result["sources"]}
    assert sorted(sources) == list(range(1, len(sources) + 1))
    for row in result["rows"]:
        assert row["agreement"] in {"similar", "different", "partial", "none"}
        for column, cell in zip(result["columns"], row["cells"], strict=True):
            assert cell["document_id"] == column["document_id"]
            for number in cell["citations"]:  # a cell only cites its own paper's passages
                assert sources[number]["document"]["id"] == column["document_id"]
    dataset = next(r for r in result["rows"] if r["key"] == "dataset")
    assert "MedQA" in dataset["cells"][0]["text"]

    overview = result["overview"]
    assert overview["text"] != "Not reported." and overview["citations"]
    assert {sources[n]["document"]["id"] for n in overview["citations"]} == set(ids)
    assert result["support"]["statements"] > 5
    assert result["progress"] is None and result["stale"] is None


async def test_papers_are_read_once_and_reused_by_later_comparisons(
    auth_client: AsyncClient,
    settings: Settings,
    library: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = FakeLLM.fill_fields

    def counting(self: FakeLLM, prompt: str) -> str:
        calls.append(prompt)
        return original(self, prompt)

    monkeypatch.setattr(FakeLLM, "fill_fields", counting)
    first = await compare(auth_client, settings, [library["lora"], library["retrieval"]])
    assert len(calls) == 2 * 4 + 1  # 4 section groups per paper + the overview
    calls.clear()

    again = await compare(auth_client, settings, [library["retrieval"], library["lora"]])
    assert again["id"] == first["id"] and calls == []  # same papers in any order: cached

    third = await compare(auth_client, settings, [library["lora"], library["notes"]])
    assert third["status"] == "ready"
    assert len(calls) == 4 + 1  # only the new paper is read
    assert third["trace"]["papers"][0]["cached"] is True

    forced = await compare(
        auth_client, settings, [library["lora"], library["retrieval"]], force=True
    )
    assert forced["id"] != first["id"]


async def test_methodology_comparison(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    result = await compare(
        auth_client, settings, [library["lora"], library["retrieval"]], kind="methodology"
    )
    assert result["status"] == "ready" and result["kind"] == "methodology"
    assert result["title"].startswith("Methodology: ")
    assert [r["key"] for r in result["rows"]] == [f.key for f in ROWS[ComparisonKind.METHODOLOGY]]


@pytest.mark.parametrize("count", [1, 6])
async def test_two_to_five_papers(
    auth_client: AsyncClient, library: dict[str, str], count: int
) -> None:
    ids = ([library["lora"]] * 6)[:count]
    response = await auth_client.post("/api/v1/comparisons", json={"document_ids": ids})
    assert response.status_code == 422


async def test_duplicates_and_other_users_papers_are_refused(
    auth_client: AsyncClient, client: AsyncClient, library: dict[str, str]
) -> None:
    same = [library["lora"], library["lora"]]
    response = await auth_client.post("/api/v1/comparisons", json={"document_ids": same})
    assert response.status_code == 422
    assert "once" in response.json()["error"]["message"]

    other = await register(client)
    headers = {"Authorization": f"Bearer {other['access_token']}"}
    response = await client.post(
        "/api/v1/comparisons",
        json={"document_ids": [library["lora"], library["retrieval"]]},
        headers=headers,
    )
    assert response.status_code == 404


async def test_failure_is_saved_and_listing_and_deleting_work(
    auth_client: AsyncClient,
    settings: Settings,
    library: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def broken(self: FakeLLM, messages: Any, params: Any) -> Any:
        raise LLMError("Can't reach Ollama. Is it running?", detail="Start Ollama")
        yield  # pragma: no cover - makes this an async generator

    monkeypatch.setattr(FakeLLM, "stream", broken)
    failed = await compare(auth_client, settings, [library["lora"], library["retrieval"]])
    assert failed["status"] == "failed"
    assert failed["error_message"] == "Can't reach Ollama. Is it running?"
    assert failed["error_hint"] == "Start Ollama"
    assert (await jobs_of(auth_client, "comparison.generate"))[0]["status"] == "failed"

    listed = (await auth_client.get("/api/v1/comparisons")).json()
    assert [c["id"] for c in listed] == [failed["id"]]
    only_notes = await auth_client.get(f"/api/v1/comparisons?document_id={library['notes']}")
    assert only_notes.json() == []

    assert (await auth_client.delete(f"/api/v1/comparisons/{failed['id']}")).status_code == 204
    assert (await auth_client.get(f"/api/v1/comparisons/{failed['id']}")).status_code == 404


async def test_deleted_paper_is_flagged(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    result = await compare(auth_client, settings, [library["lora"], library["retrieval"]])
    assert (
        await auth_client.delete(f"/api/v1/documents/{library['retrieval']}")
    ).status_code == 204
    after = (await auth_client.get(f"/api/v1/comparisons/{result['id']}")).json()
    assert after["stale"] == "A paper in this comparison was deleted."
    assert [c["deleted"] for c in after["columns"]] == [False, True]
    deleted_sources = [s for s in after["sources"] if s["letter"] == "B"]
    assert deleted_sources and all(s["document"]["id"] is None for s in deleted_sources)
