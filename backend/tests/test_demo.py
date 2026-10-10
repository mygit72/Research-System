"""Demo mode: the synthetic sample papers load through the normal pipeline, once."""

from __future__ import annotations

from httpx import AsyncClient

from app.core.config import Settings
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"


async def test_sample_papers_are_added_once_and_labelled_synthetic(
    auth_client: AsyncClient, settings: Settings
) -> None:
    first = await auth_client.post(f"{API}/demo/sample-papers")
    assert first.status_code == 202, first.text
    body = first.json()
    assert body["added"] == 3 and len(body["document_ids"]) == 3
    await get_dispatcher(settings).drain()

    papers = (await auth_client.get(f"{API}/documents")).json()["items"]
    assert len(papers) == 3 and all(p["status"] == "ready" for p in papers)
    titles = {p["title"] for p in papers}
    assert "Low-Rank Adapters for Efficient Domain Adaptation of Language Models" in titles
    detail = (await auth_client.get(f"{API}/documents/{body['document_ids'][0]}")).json()
    assert detail["metadata"]["arxiv_id"] is None  # made-up ids aren't stamped on demo copies

    collection = (await auth_client.get(f"{API}/collections/{body['collection_id']}")).json()
    assert collection["name"] == "Sample papers" and collection["paper_count"] == 3

    again = (await auth_client.post(f"{API}/demo/sample-papers")).json()
    assert again["added"] == 0 and again["collection_id"] == body["collection_id"]

    hits = (
        await auth_client.post(f"{API}/search", json={"query": "synthetic sample paper"})
    ).json()["results"]
    # One-page papers keep their running header (removal needs it repeated across pages), so
    # the label is part of the searchable text: a cited passage shows it's synthetic.
    assert any("not a real publication" in h["text"] for h in hits)
