"""Chunking → embedding → vector index, end to end through the API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.embeddings import EmbeddingError, HashingEmbeddingProvider
from app.services.vectorstore import VectorFilter, collection_name, get_vector_store
from app.workers.dispatcher import get_dispatcher

PDF = "application/pdf"


async def upload(
    client: AsyncClient, settings: Settings, name: str, data: bytes, mime: str = PDF
) -> str:
    response = await client.post("/api/v1/documents", files=[("files", (name, data, mime))])
    assert response.status_code == 201, response.text
    await get_dispatcher(settings).drain()
    return str(response.json()["items"][0]["id"])


@pytest.fixture
def papers(tmp_path: Path) -> dict[str, bytes]:
    return {
        "retrieval": sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes(),
        "lora": sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes(),
        "retrieval_md": sp.write_sample_markdown(
            sp.RETRIEVAL_PAPER, tmp_path / "r.md"
        ).read_bytes(),
    }


async def last_job_result(client: AsyncClient) -> dict[str, Any]:
    return dict((await client.get("/api/v1/jobs?limit=1")).json()["items"][0]["result"])


async def test_upload_indexes_chunks_with_citation_anchors(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    doc_id = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert detail["index_status"] == "indexed"
    version = detail["version"]
    assert version["embedding_model"] == "hashing-v1-384"
    assert version["chunking_strategy"] == "section_aware"
    assert version["chunk_count"] > 5

    chunks = (await auth_client.get(f"/api/v1/documents/{doc_id}/chunks?limit=500")).json()
    assert chunks["total"] == version["chunk_count"]
    items = chunks["items"]
    assert [c["chunk_index"] for c in items] == list(range(len(items)))
    assert {"table", "equation", "caption"} <= {c["kind"] for c in items}
    for chunk in items:
        assert chunk["page_start"] >= 1 and chunk["char_end"] > chunk["char_start"]
        assert chunk["token_count"] <= settings.chunk_size or chunk["kind"] in {"table", "equation"}
        if chunk["kind"] == "text" and chunk["section_kind"] != "preamble":
            assert chunk["boxes"], "PDF chunks carry highlight boxes"
    method = next(c for c in items if c["section_title"] == "Training Objective")
    assert "3 Method › 3.1 Training Objective" in method["context_header"]

    job = await last_job_result(auth_client)
    assert job["index"]["status"] == "indexed"
    assert job["index"]["chunks"] == version["chunk_count"]

    store = get_vector_store(settings)
    name = collection_name("chunks", "hashing-v1-384", 384)
    me = (await auth_client.get("/api/v1/users/me")).json()
    import uuid

    assert store.count(name, VectorFilter(user_id=uuid.UUID(me["id"]))) == version["chunk_count"]
    query = HashingEmbeddingProvider().embed_query(
        "reciprocal rank fusion of BM25 and dense rankings"
    )
    hits = store.search(name, query, VectorFilter(user_id=uuid.UUID(me["id"])), 3)
    top = next(c for c in items if c["id"] == str(hits[0].id))
    assert "fusion" in top["text"].lower()


async def test_reprocessing_reuses_cached_embeddings(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    doc_id = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    first = await last_job_result(auth_client)
    assert first["index"]["embedded"] > 0

    await auth_client.post(f"/api/v1/documents/{doc_id}/process")
    await get_dispatcher(settings).drain()
    second = await last_job_result(auth_client)
    assert second["index"]["embedded"] == 0
    assert second["index"]["cached"] == first["index"]["embedded"]


async def test_similar_papers_with_reasons(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    retrieval = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    lone = (await auth_client.get(f"/api/v1/documents/{retrieval}/similar")).json()
    assert lone == {"status": "no_other_papers", "items": []}

    await upload(auth_client, settings, "l.pdf", papers["lora"])
    md = await upload(auth_client, settings, "r.md", papers["retrieval_md"], "text/markdown")
    result = (await auth_client.get(f"/api/v1/documents/{retrieval}/similar")).json()
    assert result["status"] == "ok"
    ranked = [item["document"]["id"] for item in result["items"]]
    assert ranked[0] == md  # same paper in another format is the nearest neighbour
    top = result["items"][0]
    assert top["score"] > result["items"][1]["score"]
    assert any("Shared keywords" in r or "Both discuss" in r for r in top["reasons"])


async def test_indexing_failure_keeps_paper_readable_and_can_be_retried(
    auth_client: AsyncClient,
    settings: Settings,
    papers: dict[str, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: HashingEmbeddingProvider, texts: list[str]) -> np.ndarray:
        raise EmbeddingError("The embedding model “x” couldn't be loaded.", detail="offline")

    # A scoped patch: `monkeypatch.undo()` would also revert conftest's settings patch and
    # send the retry to the real .env configuration (real model, dev data directory).
    with monkeypatch.context() as patch:
        patch.setattr(HashingEmbeddingProvider, "embed_documents", broken)
        doc_id = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
        detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
        assert detail["status"] == "ready"  # reading still works
        assert detail["index_status"] == "failed"
        assert "couldn't be loaded" in detail["index_error"]
        similar = (await auth_client.get(f"/api/v1/documents/{doc_id}/similar")).json()
        assert similar["status"] == "not_indexed"

    retried = await auth_client.post(f"/api/v1/documents/{doc_id}/reindex")
    assert retried.status_code == 200
    await get_dispatcher(settings).drain()
    detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert detail["index_status"] == "indexed"
    assert detail["index_error"] is None


async def test_delete_removes_vectors(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    import uuid

    doc_id = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    me = uuid.UUID((await auth_client.get("/api/v1/users/me")).json()["id"])
    store = get_vector_store(settings)
    chunks = collection_name("chunks", "hashing-v1-384", 384)
    documents = collection_name("documents", "hashing-v1-384", 384)
    assert store.count(chunks, VectorFilter(user_id=me)) > 0
    assert (await auth_client.delete(f"/api/v1/documents/{doc_id}")).status_code == 204
    assert store.count(chunks, VectorFilter(user_id=me)) == 0
    assert store.count(documents, VectorFilter(user_id=me)) == 0


async def test_chunks_are_private(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    doc_id = await upload(auth_client, settings, "r.pdf", papers["retrieval"])
    other = await client.post(
        "/api/v1/auth/register", json={"email": "eve@example.com", "password": "correct-horse-42"}
    )
    headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    for path in ("chunks", "similar"):
        response = await client.get(f"/api/v1/documents/{doc_id}/{path}", headers=headers)
        assert response.status_code == 404


async def test_ai_status(auth_client: AsyncClient) -> None:
    status = (await auth_client.get("/api/v1/ai/status")).json()
    assert status["embedding"]["provider"] == "hashing"
    assert status["chunking"]["strategy"] == "section_aware"
    assert status["vector_store"] == {"backend": "qdrant", "mode": "embedded"}


async def test_concurrent_uploads_all_get_indexed(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, bytes]
) -> None:
    """Regression: papers processed at the same time sometimes failed to index."""
    for _ in range(3):
        files = [
            ("files", ("r.pdf", papers["retrieval"], PDF)),
            ("files", ("l.pdf", papers["lora"], PDF)),
            ("files", ("r.md", papers["retrieval_md"], "text/markdown")),
        ]
        assert (await auth_client.post("/api/v1/documents", files=files)).status_code == 201
        await get_dispatcher(settings).drain()
    documents = (await auth_client.get("/api/v1/documents?limit=50")).json()["items"]
    assert len(documents) == 9
    assert {d["index_status"] for d in documents} == {"indexed"}, [
        (d["original_filename"], d["index_error"]) for d in documents
    ]
