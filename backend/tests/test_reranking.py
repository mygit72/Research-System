"""Reranking: providers, score cache, and the rerank stage of search."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.demo import sample_papers as sp
from app.services.reranking import (
    ApiReranker,
    LexicalReranker,
    RerankError,
    ScoreCache,
    get_reranker,
    score_cache,
    sigmoid,
)
from tests.test_indexing_api import upload

# --- providers --------------------------------------------------------------------------------


def test_sigmoid_is_stable() -> None:
    assert sigmoid(0) == 0.5
    assert sigmoid(800) == pytest.approx(1.0) and sigmoid(-800) == pytest.approx(0.0)


def test_lexical_reranker_rewards_coverage_and_proximity() -> None:
    reranker = LexicalReranker()
    scores = reranker.score(
        "reciprocal rank fusion",
        [
            "We use reciprocal rank fusion.",  # all terms, adjacent
            "Reciprocal ... many words in between ... rank ... more words ... fusion",
            "Only fusion here.",
            "Nothing relevant.",
        ],
    )
    assert scores[0] > scores[1] > scores[2] > scores[3] == 0.0
    assert reranker.score("the of", ["anything"]) == [0.0]


def _rerank_transport(calls: list[dict[str, Any]], fail_first: int = 0) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) <= fail_first:
            return httpx.Response(503, headers={"retry-after": "0"})
        if body["model"] == "bad":
            return httpx.Response(401, json={"error": "invalid key"})
        results = [
            {"index": i, "relevance_score": 1.0 / (1 + len(doc))}
            for i, doc in enumerate(body["documents"])
        ]
        return httpx.Response(
            200, json={"results": sorted(results, key=lambda r: -r["relevance_score"])}
        )

    return httpx.MockTransport(handler)


def test_api_reranker_maps_scores_back_to_input_order_and_retries() -> None:
    calls: list[dict[str, Any]] = []
    reranker = ApiReranker(
        "jina-reranker-v2", "key", "https://api.example/v1/", transport=_rerank_transport(calls, 1)
    )
    passages = ["x" * n for n in (5, 1, 30)]
    scores = reranker.score("query", passages)
    assert scores == pytest.approx([1 / 6, 1 / 2, 1 / 31])  # by input index, not response order
    assert len(calls) == 2  # one 503 retried
    assert calls[-1]["top_n"] == 3 and calls[-1]["query"] == "query"

    many = reranker.score("q", ["p"] * 150)  # split into API-sized batches
    assert len(many) == 150


def test_api_reranker_errors_are_user_safe() -> None:
    reranker = ApiReranker("bad", "key", "https://api.example/v1", transport=_rerank_transport([]))
    with pytest.raises(RerankError) as error:
        reranker.score("q", ["p"])
    assert error.value.user_message == "The reranking service rejected the request."
    assert "invalid key" in (error.value.detail or "")


def test_reranker_selection_and_local_only(settings: Settings) -> None:
    assert get_reranker(settings.model_copy(update={"reranker_provider": "none"})) is None
    assert isinstance(
        get_reranker(settings.model_copy(update={"reranker_provider": "lexical"})), LexicalReranker
    )
    with pytest.raises(ServiceUnavailableError, match="LOCAL_ONLY"):
        get_reranker(
            settings.model_copy(
                update={
                    "reranker_provider": "api",
                    "local_only": True,
                    "reranker_api_key": SecretStr("k"),
                }
            )
        )
    with pytest.raises(ServiceUnavailableError, match="Unknown"):
        get_reranker(settings.model_copy(update={"reranker_provider": "magic"}))


def test_score_cache_only_computes_new_pairs() -> None:
    class Counting(LexicalReranker):
        def __init__(self) -> None:
            self.calls: list[int] = []

        def score(self, query: str, passages: list[str]) -> list[float]:
            self.calls.append(len(passages))
            return super().score(query, passages)

    reranker, cache = Counting(), ScoreCache(max_entries=3)
    first, cached = cache.score(reranker, "rank fusion", ["rank fusion", "fusion", "other"])
    assert cached == 0 and reranker.calls == [3]
    again, cached = cache.score(reranker, "rank fusion", ["fusion", "new passage", "rank fusion"])
    assert cached == 2 and reranker.calls == [3, 1]  # only "new passage" was scored
    assert again[0] == first[1] and again[2] == first[0]
    cache.score(reranker, "another query", ["rank fusion"])  # LRU evicts the oldest entry
    assert len(cache) == 3


# --- search integration -----------------------------------------------------------------------


@pytest.fixture
def rerank_settings(settings: Settings) -> Settings:
    settings.reranker_provider = "lexical"
    settings.rerank_candidates = 30
    score_cache.clear()
    return settings


@pytest.fixture
async def library(
    auth_client: AsyncClient, rerank_settings: Settings, tmp_path: Path
) -> dict[str, str]:
    retrieval = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    lora = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return {
        "retrieval": await upload(auth_client, rerank_settings, "r.pdf", retrieval),
        "lora": await upload(auth_client, rerank_settings, "l.pdf", lora),
    }


async def search(client: AsyncClient, query: str, **body: Any) -> dict[str, Any]:
    response = await client.post("/api/v1/search", json={"query": query, **body})
    assert response.status_code == 200, response.text
    return dict(response.json())


async def test_search_reranks_fused_candidates(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    query = "rank fusion of sparse and dense retrievers"
    result = await search(auth_client, query, debug=True, limit=10)
    assert result["reranker"] == "lexical-overlap-v1"
    hits = result["results"]
    assert all(h["score_kind"] == "rerank" for h in hits)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)  # ordered by the reranker
    assert {"rerank", "fusion"} <= set(result["timings_ms"])

    trace = result["trace"]
    reranked = trace["stages"]["reranked"]
    assert [e["chunk_id"] for e in reranked][: len(hits)] == [h["chunk_id"] for h in hits]
    assert [e["fused_rank"] for e in reranked] == [h["fused_rank"] for h in hits] + [
        e["fused_rank"] for e in reranked[len(hits) :]
    ]
    assert trace["parameters"]["reranker"] == "lexical-overlap-v1"
    # Reranking only reorders the fused candidates: same set, possibly different order.
    fused_ids = [e["chunk_id"] for e in trace["stages"]["fused"]][: len(reranked)]
    assert sorted(e["chunk_id"] for e in reranked) == sorted(fused_ids)
    assert any(h["fused_rank"] != h["rank"] for h in hits)  # it actually moved something


async def test_rerank_can_be_turned_off_per_request(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    result = await search(auth_client, "rank fusion", rerank=False)
    assert result["reranker"] is None
    assert all(h["score_kind"] == "rrf" and h["fused_rank"] == h["rank"] for h in result["results"])
    assert "rerank" not in result["timings_ms"]


async def test_repeated_search_reuses_cached_scores(
    auth_client: AsyncClient, library: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    await search(auth_client, "low-rank adapters memory")
    calls: list[int] = []
    original = LexicalReranker.score

    def counting(self: LexicalReranker, query: str, passages: list[str]) -> list[float]:
        calls.append(len(passages))
        return original(self, query, passages)

    monkeypatch.setattr(LexicalReranker, "score", counting)
    again = await search(auth_client, "low-rank adapters memory")
    assert again["reranker"] == "lexical-overlap-v1" and calls == []  # every pair cached


async def test_reranker_failure_keeps_fused_results(
    auth_client: AsyncClient, library: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: LexicalReranker, query: str, passages: list[str]) -> list[float]:
        raise RerankError("The reranking model couldn't be loaded.")

    monkeypatch.setattr(LexicalReranker, "score", broken)
    result = await search(auth_client, "dense retrieval failure mode")
    assert result["results"] and result["reranker"] is None
    assert result["results"][0]["score_kind"] == "rrf"
    assert "Results are in fused order" in result["warnings"][0]


async def test_explicit_rerank_without_a_reranker_warns(
    auth_client: AsyncClient, library: dict[str, str], rerank_settings: Settings
) -> None:
    rerank_settings.reranker_provider = "none"
    result = await search(auth_client, "rank fusion", rerank=True)
    assert result["reranker"] is None
    assert result["warnings"] == ["Reranking is turned off on this server."]


# --- real model (opt-in: RUN_MODEL_TESTS=1, downloads ~90 MB once) -----------------------------


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1", reason="set RUN_MODEL_TESTS=1")
def test_cross_encoder_prefers_the_answering_passage() -> None:
    from app.services.models.manager import ModelManager
    from app.services.reranking import CrossEncoderReranker

    reranker = CrossEncoderReranker("cross-encoder/ms-marco-MiniLM-L-6-v2", ModelManager(), "cpu")
    scores = reranker.score(
        "How are the sparse and dense rankings combined?",
        [
            "Dense retrieval encodes queries and passages into one vector space.",
            "The two ranked lists are fused with reciprocal rank fusion.",
            "We thank the reviewers for their comments.",
        ],
    )
    assert max(range(3), key=scores.__getitem__) == 1
    assert all(0.0 <= s <= 1.0 for s in scores)
