"""Search API end to end: keyword, semantic and hybrid over uploaded papers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.embeddings import EmbeddingError, HashingEmbeddingProvider
from tests.conftest import register
from tests.test_indexing_api import upload


@pytest.fixture
def papers(tmp_path: Path) -> dict[str, bytes]:
    return {
        "retrieval": sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes(),
        "lora": sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes(),
        "lora_md": sp.write_sample_markdown(sp.LORA_PAPER, tmp_path / "l.md").read_bytes(),
    }


@pytest.fixture
async def library(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> dict[str, str]:
    return {
        "retrieval": await upload(auth_client, settings, "r.pdf", papers["retrieval"]),
        "lora": await upload(auth_client, settings, "l.pdf", papers["lora"]),
    }


async def search(client: AsyncClient, query: str, **body: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/search", json={"query": query, **body})
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_keyword_search_finds_and_highlights_passages(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    result = await search(auth_client, "how does reciprocal rank fusion work?", mode="keyword")
    assert result["status"] == "ok"
    assert result["retrievers"] == ["bm25"]
    assert result["searched_papers"] == 2
    top = result["results"][0]
    assert top["document"]["id"] == library["retrieval"]
    assert top["document"]["year"] == 2024
    assert top["score_kind"] == "bm25" and top["matched_by"] == ["bm25"]
    highlighted = [top["text"][s:e].lower() for s, e in top["highlights"]]
    assert any("reciprocal rank fusion" in h for h in highlighted)
    start, end = top["snippet"]
    assert 0 <= start < end <= len(top["text"])
    assert top["page_start"] >= 1 and top["boxes"]
    assert {"scope", "bm25", "total"} <= set(result["timings_ms"])


async def test_stemming_matches_other_word_forms(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    result = await search(auth_client, "adapting adapter", mode="keyword")
    assert result["results"][0]["document"]["id"] == library["lora"]


async def test_hybrid_fuses_both_retrievers_and_explains_itself(
    auth_client: AsyncClient, library: dict[str, str], settings: Settings
) -> None:
    result = await search(auth_client, "low-rank adapters GPU memory", debug=True)
    assert result["mode"] == "hybrid"
    assert result["retrievers"] == ["bm25", "dense"]
    assert result["results"][0]["document"]["id"] == library["lora"]
    assert result["results"][0]["score_kind"] == "rrf"

    trace = result["trace"]
    assert trace["fusion"] == {"method": "rrf", "k": settings.rrf_k}
    assert set(trace["stages"]) == {"bm25", "dense", "fused"}
    assert "gpu" in trace["query_terms"]
    fused = trace["stages"]["fused"]
    for entry in fused:
        rrf = sum(c["rrf"] for c in entry["contributions"].values())
        assert entry["score"] == pytest.approx(rrf, abs=1e-4)
    assert [e["rank"] for e in fused] == list(range(1, len(fused) + 1))
    assert trace["stages"]["bm25"][0]["matched_terms"]
    # The fused list is what the results show, in the same order.
    assert [r["chunk_id"] for r in result["results"]] == [e["chunk_id"] for e in fused][
        : len(result["results"])
    ]


async def test_semantic_mode_uses_only_dense(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    result = await search(auth_client, "adapters", mode="semantic")
    assert result["retrievers"] == ["dense"]
    assert all(r["matched_by"] == ["dense"] for r in result["results"])
    assert result["results"][0]["score_kind"] == "cosine"


async def test_filters_apply_inside_retrieval(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes], library: dict[str, str]
) -> None:
    md = await upload(auth_client, settings, "l.md", papers["lora_md"], "text/markdown")
    query = "adapters fine-tuning retrieval"

    only_2024 = await search(auth_client, query, filters={"year_from": 2024})
    assert {r["document"]["id"] for r in only_2024["results"]} == {library["retrieval"]}
    assert only_2024["searched_papers"] == 1

    chosen = await search(auth_client, query, filters={"document_ids": [library["lora"]]})
    assert {r["document"]["id"] for r in chosen["results"]} == {library["lora"]}

    markdown = await search(auth_client, query, filters={"doc_types": ["markdown"]})
    assert {r["document"]["id"] for r in markdown["results"]} == {md}

    by_author = await search(auth_client, query, filters={"authors": ["maya lindqvist"]})
    assert {r["document"]["id"] for r in by_author["results"]} == {library["retrieval"]}

    sections = await search(auth_client, query, filters={"section_kinds": ["abstract"]})
    assert sections["results"] and {r["section_kind"] for r in sections["results"]} == {"abstract"}

    nothing = await search(auth_client, query, filters={"year_to": 1999})
    assert nothing["status"] == "no_results" and nothing["searched_papers"] == 0


async def test_reference_lists_are_excluded_unless_asked_for(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    # "Zaragoza" only appears in the retrieval paper's reference list.
    default = await search(auth_client, "Zaragoza", mode="keyword")
    assert default["status"] == "no_results"
    included = await search(
        auth_client, "Zaragoza", mode="keyword", filters={"include_references": True}
    )
    assert included["results"][0]["section_kind"] == "references"


async def test_users_never_see_each_others_passages(
    client: AsyncClient, auth_client: AsyncClient, library: dict[str, str]
) -> None:
    other = await register(client, "other@example.com")
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    result = await search(client, "reciprocal rank fusion")
    assert result["status"] == "empty_library" and result["results"] == []
    # Even naming the other user's paper explicitly finds nothing.
    sneaky = await search(
        client, "reciprocal rank fusion", filters={"document_ids": [library["retrieval"]]}
    )
    assert sneaky["results"] == []


async def test_index_stays_in_sync_with_deletes_and_new_papers(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    retrieval = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    assert (await search(auth_client, "adapters", mode="keyword"))["status"] == "no_results"
    lora = await upload(auth_client, settings, "l.pdf", papers["lora"])  # added after first search
    result = await search(auth_client, "adapters", mode="keyword")
    assert result["results"][0]["document"]["id"] == lora

    assert (await auth_client.delete(f"/api/v1/documents/{lora}")).status_code == 204
    for mode in ("keyword", "semantic", "hybrid"):
        after = await search(auth_client, "low-rank adapters", mode=mode)
        assert lora not in {r["document"]["id"] for r in after["results"]}, mode
    assert (await search(auth_client, "fusion", mode="keyword"))["results"][0]["document"][
        "id"
    ] == retrieval


async def test_hybrid_degrades_to_keyword_when_embeddings_fail(
    auth_client: AsyncClient, library: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: HashingEmbeddingProvider, text: str) -> np.ndarray:
        raise EmbeddingError("The embedding model couldn't be loaded.")

    with monkeypatch.context() as patch:
        patch.setattr(HashingEmbeddingProvider, "embed_query", broken)
        result = await search(auth_client, "rank fusion unavailable-model-query")
        assert result["retrievers"] == ["bm25"]
        assert result["results"]
        assert "keyword matches only" in result["warnings"][0]

        semantic = await auth_client.post(
            "/api/v1/search", json={"query": "rank fusion other query", "mode": "semantic"}
        )
        assert semantic.status_code == 503
        assert "Keyword search still works" in semantic.json()["error"]["hint"]


async def test_validation(auth_client: AsyncClient) -> None:
    for body in (
        {"query": ""},
        {"query": "   "},
        {"query": "x" * 501},
        {"query": "ok", "mode": "magic"},
        {"query": "ok", "filters": {"year_from": 2024, "year_to": 2020}},
        {"query": "ok", "limit": 0},
    ):
        response = await auth_client.post("/api/v1/search", json=body)
        assert response.status_code == 422, body
    assert (await search(auth_client, "anything"))["status"] == "empty_library"


async def test_search_requires_authentication(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/search", json={"query": "x"})).status_code == 401


async def test_facets_describe_the_library(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    facets = (await auth_client.get("/api/v1/search/facets")).json()
    assert facets["papers"] == facets["indexed_papers"] == 2
    assert (facets["year_min"], facets["year_max"]) == (2023, 2024)
    assert facets["doc_types"] == [{"value": "pdf", "count": 2}]
    assert {"value": "Maya Lindqvist", "count": 1} in facets["authors"]
    assert {f["value"] for f in facets["section_kinds"]} >= {"abstract", "method", "references"}
    assert "LoRA" in facets["suggestions"] or "hybrid search" in facets["suggestions"]
