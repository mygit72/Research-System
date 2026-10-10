"""Knowledge API: entities, related work, graph, authors, timeline, topic clustering."""

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


def by_name(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in rows}


async def test_processing_links_papers_to_entities_with_evidence(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    job = (await ok(await auth_client.get(f"{API}/jobs?limit=1")))["items"][0]
    assert job["result"]["entities"]["status"] == "ok"  # extracted during processing

    rala = by_name(await ok(await auth_client.get(f"{API}/documents/{library['rala']}/entities")))
    assert rala["RALA"]["relation"] == "proposes" and rala["RALA"]["type"] == "method"
    assert rala["LoRA"]["relation"] == "uses"
    assert rala["SciQA-2400"]["type"] == "dataset" and rala["SciQA-2400"]["relation"] == "uses"
    assert rala["Natural Questions"]["relation"] == "uses"
    assert rala["Exact match"]["type"] == "metric"
    evidence = rala["SciQA-2400"]["evidence"][0]
    assert "SciQA-2400" in evidence["quote"] and evidence["page"] >= 1
    assert rala["SciQA-2400"]["paper_count"] == 3  # discovered once, linked everywhere

    datasets = by_name(
        await ok(await auth_client.get(f"{API}/entities", params={"type": "dataset"}))
    )
    assert datasets["SciQA-2400"]["paper_count"] == 3
    assert datasets["SciQA-2400"]["source"] == "discovered"
    detail = await ok(await auth_client.get(f"{API}/entities/{datasets['SciQA-2400']['id']}"))
    assert {p["id"] for p in detail["papers"]} == set(library.values())
    assert any(r["name"] == "LoRA" for r in detail["related"])
    assert [y["year"] for y in detail["years"]] == [2023, 2024]

    nq = datasets["Natural Questions"]
    nq_detail = await ok(await auth_client.get(f"{API}/entities/{nq['id']}"))
    assert nq_detail["info"]["task"] == "Open-domain question answering"  # built-in catalog

    found = await ok(await auth_client.get(f"{API}/entities", params={"q": "rank"}))
    assert "Reciprocal rank fusion" in by_name(found)


async def test_related_work_citations_and_authors(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    related = await ok(await auth_client.get(f"{API}/documents/{library['rala']}/related"))
    cites = {c["id"]: c["match"] for c in related["cites"]}
    assert cites == {library["retrieval"]: "arxiv", library["lora"]: "title"}
    assert related["cited_by"] == []
    same = {p["id"]: p["shared_authors"] for p in related["same_authors"]}
    assert same == {library["retrieval"]: ["Priya Raman"], library["lora"]: ["Chen Wei"]}
    shared = {p["id"]: p["shared"] for p in related["shared_entities"]}
    assert "SciQA-2400" in shared[library["retrieval"]]["dataset"]

    lora = await ok(await auth_client.get(f"{API}/documents/{library['lora']}/related"))
    assert [c["id"] for c in lora["cited_by"]] == [library["rala"]]

    authors = {a["name"]: a for a in await ok(await auth_client.get(f"{API}/authors"))}
    assert authors["Priya Raman"]["paper_count"] == 2
    assert authors["Priya Raman"]["institutions"] == [
        "Department of Computer Science, Northbridge University"
    ]
    priya = await ok(await auth_client.get(f"{API}/authors/{authors['Priya Raman']['key']}"))
    coauthors = {c["name"]: c["shared_papers"] for c in priya["coauthors"]}
    assert coauthors["Chen Wei"] == 1 and coauthors["Maya Lindqvist"] == 1
    assert [y["year"] for y in priya["years"]] == [2024]
    assert any(e["name"] == "SciQA-2400" for e in priya["entities"])
    await ok(await auth_client.get(f"{API}/authors/nobody"), 404)


async def test_graph_overview_expand_search_and_path(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    graph = await ok(await auth_client.get(f"{API}/graph", params={"limit": 30}))
    types = {n["type"] for n in graph["nodes"]}
    assert {"paper", "dataset", "method", "author"} <= types
    relations = {e["relation"] for e in graph["edges"]}
    assert {"cites", "authored_by", "uses_dataset", "proposes"} <= relations
    assert "mentions" not in relations
    assert graph["paper_count"] == 3 and graph["entity_status"]["citations"] == 2
    ids = {n["id"] for n in graph["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in graph["edges"])

    only = await ok(await auth_client.get(f"{API}/graph", params={"types": "paper,dataset"}))
    assert {n["type"] for n in only["nodes"]} <= {"paper", "dataset"}
    await ok(await auth_client.get(f"{API}/graph", params={"types": "planet"}), 422)

    hits = await ok(await auth_client.get(f"{API}/graph/search", params={"q": "sciqa"}))
    node = hits[0]
    assert node["label"] == "SciQA-2400" and node["type"] == "dataset"
    expanded = await ok(
        await auth_client.get(f"{API}/graph/neighbors", params={"node": node["id"]})
    )
    assert {n["id"] for n in expanded["nodes"]} >= {f"paper:{d}" for d in library.values()}

    path = await ok(
        await auth_client.get(
            f"{API}/graph/path",
            params={
                "source": f"paper:{library['lora']}",
                "target": f"paper:{library['retrieval']}",
            },
        )
    )
    assert path["nodes"][0]["id"] == f"paper:{library['lora']}"
    assert path["nodes"][-1]["id"] == f"paper:{library['retrieval']}"
    assert len(path["edges"]) == len(path["nodes"]) - 1

    ego = await ok(await auth_client.get(f"{API}/papers/{library['rala']}/knowledge-graph"))
    assert f"paper:{library['retrieval']}" in {n["id"] for n in ego["nodes"]}  # cited


async def test_timeline_by_year_with_filters(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    timeline = await ok(await auth_client.get(f"{API}/timeline"))
    years = {y["year"]: y for y in timeline["years"]}
    assert set(years) == {2023, 2024}
    assert [p["id"] for p in years[2023]["papers"]] == [library["lora"]]
    rala = next(p for p in years[2024]["papers"] if p["id"] == library["rala"])
    assert [e["name"] for e in rala["proposes"]] == ["RALA"]
    assert "LoRA" in {e["name"] for e in years[2023]["first_seen"]}
    assert "LoRA" not in {e["name"] for e in years[2024]["first_seen"]}  # seen in 2023 already

    priya = next(a for a in timeline["filters"]["authors"] if a["name"] == "Priya Raman")
    filtered = await ok(await auth_client.get(f"{API}/timeline", params={"author": priya["key"]}))
    assert filtered["paper_count"] == 2
    lora = next(m for m in timeline["filters"]["methods"] if m["name"] == "LoRA")
    by_method = await ok(await auth_client.get(f"{API}/timeline", params={"entity_id": lora["id"]}))
    assert by_method["paper_count"] == 2


async def test_topic_clustering_runs_and_is_named(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    assert (await ok(await auth_client.get(f"{API}/topics")))["clustering"] is None

    run = await ok(await auth_client.post(f"{API}/topics", json={"method": "kmeans", "k": 2}), 201)
    assert len(run["clusters"]) == 2 and len(run["points"]) == 3
    assert sorted(len(c["document_ids"]) for c in run["clusters"]) == [1, 2]
    assert all(c["name_source"] == "terms" and c["terms"] for c in run["clusters"])
    assert run["naming_status"] == "pending" and run["stale"] is None
    await get_dispatcher(settings).drain()

    latest = (await ok(await auth_client.get(f"{API}/topics")))["clustering"]
    assert latest["id"] == run["id"] and latest["naming_status"] == "done"
    assert all(c["name_source"] == "model" for c in latest["clusters"])
    assert latest["naming_model"]

    # Topics show up in the graph and the timeline filters.
    graph = await ok(await auth_client.get(f"{API}/graph"))
    assert sum(1 for n in graph["nodes"] if n["type"] == "topic") == 2
    timeline = await ok(await auth_client.get(f"{API}/timeline"))
    assert len(timeline["filters"]["topics"]) == 2
    topic = timeline["filters"]["topics"][0]
    filtered = await ok(await auth_client.get(f"{API}/timeline", params={"topic": topic["id"]}))
    assert filtered["paper_count"] == topic["size"]

    for body in ({"method": "auto"}, {"method": "agglomerative", "k": 9}, {"method": "hdbscan"}):
        other = await ok(await auth_client.post(f"{API}/topics", json=body), 201)
        assert len(other["points"]) == 3
        assert other["quality"]["noise"] == sum(1 for p in other["points"] if p["cluster"] == -1)
    await ok(await auth_client.post(f"{API}/topics", json={"method": "spectral"}), 422)


async def test_topics_need_three_papers_and_go_stale(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    await ok(await auth_client.post(f"{API}/topics", json={}), 201)
    await get_dispatcher(settings).drain()
    await ok(await auth_client.delete(f"{API}/documents/{library['lora']}"), 204)
    await get_dispatcher(settings).drain()
    latest = (await ok(await auth_client.get(f"{API}/topics")))["clustering"]
    assert "3 → 2 papers" in latest["stale"]
    response = await auth_client.post(f"{API}/topics", json={})
    assert response.status_code == 422 and "at least 3" in response.json()["error"]["message"]


async def test_deleting_a_paper_removes_its_links(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    await ok(await auth_client.delete(f"{API}/documents/{library['rala']}"), 204)
    await get_dispatcher(settings).drain()
    methods = by_name(await ok(await auth_client.get(f"{API}/entities", params={"type": "method"})))
    assert "RALA" not in methods  # only that paper linked it: the entity is gone
    datasets = by_name(
        await ok(await auth_client.get(f"{API}/entities", params={"type": "dataset"}))
    )
    assert datasets["SciQA-2400"]["paper_count"] == 2
    related = await ok(await auth_client.get(f"{API}/documents/{library['lora']}/related"))
    assert related["cited_by"] == []


async def test_knowledge_is_private(
    auth_client: AsyncClient, client: AsyncClient, library: dict[str, str]
) -> None:
    datasets = await ok(await auth_client.get(f"{API}/entities", params={"type": "dataset"}))
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    assert await ok(await client.get(f"{API}/entities")) == []
    assert (await ok(await client.get(f"{API}/graph")))["nodes"] == []
    assert await ok(await client.get(f"{API}/authors")) == []
    await ok(await client.get(f"{API}/entities/{datasets[0]['id']}"), 404)
    await ok(await client.get(f"{API}/documents/{library['rala']}/related"), 404)
    await ok(await client.get(f"{API}/papers/{library['rala']}/knowledge-graph"), 404)
