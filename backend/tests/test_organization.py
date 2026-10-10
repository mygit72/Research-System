"""Collections, tags, notes, bookmarks, reading status, filters and citation export."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.citation_export import Reference, bibtex, citation_keys, ris
from tests.conftest import register
from tests.test_indexing_api import upload

API = "/api/v1"


@pytest.fixture
async def library(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    retrieval = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    lora = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes()
    return {
        "retrieval": await upload(auth_client, settings, "r.pdf", retrieval),
        "lora": await upload(auth_client, settings, "l.pdf", lora),
    }


async def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


async def papers(client: AsyncClient, **params: Any) -> list[str]:
    page = await ok(await client.get(f"{API}/documents", params=params))
    return [d["id"] for d in page["items"]]


# --- collections ---------------------------------------------------------------------------------


async def test_collections_hold_papers_and_keep_them_when_deleted(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    thesis = await ok(
        await auth_client.post(
            f"{API}/collections",
            json={"name": "  Thesis ch. 2 ", "kind": "thesis", "document_ids": [library["lora"]]},
        ),
        201,
    )
    assert thesis["name"] == "Thesis ch. 2" and thesis["kind"] == "thesis"
    assert thesis["paper_count"] == 1

    added = await ok(
        await auth_client.post(
            f"{API}/collections/{thesis['id']}/documents",
            json={"document_ids": [library["lora"], library["retrieval"]]},
        )
    )
    assert added == {"added": 1, "paper_count": 2}  # already-present papers are skipped

    detail = await ok(await auth_client.get(f"{API}/collections/{thesis['id']}"))
    assert [d["id"] for d in detail["documents"]] == [library["lora"], library["retrieval"]]
    assert await papers(auth_client, collection_id=thesis["id"]) != []

    renamed = await ok(
        await auth_client.patch(
            f"{API}/collections/{thesis['id']}", json={"name": "Thesis", "description": "Ch. 2"}
        )
    )
    assert renamed["name"] == "Thesis" and renamed["description"] == "Ch. 2"

    await ok(
        await auth_client.delete(f"{API}/collections/{thesis['id']}/documents/{library['lora']}"),
        204,
    )
    assert (await ok(await auth_client.get(f"{API}/collections")))[0]["paper_count"] == 1

    await ok(await auth_client.delete(f"{API}/collections/{thesis['id']}"), 204)
    assert await ok(await auth_client.get(f"{API}/collections")) == []
    assert len(await papers(auth_client)) == 2  # the papers stay in the library


async def test_collections_are_private(
    auth_client: AsyncClient, client: AsyncClient, library: dict[str, str]
) -> None:
    mine = await ok(await auth_client.post(f"{API}/collections", json={"name": "Mine"}), 201)
    other = await register(client)
    headers = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"{API}/collections/{mine['id']}", headers=headers)).status_code == 404
    response = await client.post(
        f"{API}/collections",
        json={"name": "Theirs", "document_ids": [library["lora"]]},
        headers=headers,
    )
    assert response.status_code == 404  # can't add someone else's paper


# --- tags, reading status, bookmarks -------------------------------------------------------------


async def test_tags_are_case_insensitive_and_filter_the_library(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    lora, retrieval = library["lora"], library["retrieval"]
    org = await ok(
        await auth_client.put(
            f"{API}/documents/{lora}/tags", json={"names": ["PEFT", "#peft", " to cite "]}
        )
    )
    assert [t["name"] for t in org["tags"]] == ["PEFT", "to cite"]
    await ok(
        await auth_client.put(f"{API}/documents/{retrieval}/tags", json={"names": ["to cite"]})
    )

    tags = {t["name"]: t for t in await ok(await auth_client.get(f"{API}/tags"))}
    assert tags["to cite"]["paper_count"] == 2 and tags["PEFT"]["paper_count"] == 1
    assert await papers(auth_client, tag="peft") == [lora]
    assert set(await papers(auth_client, tag=["peft", "TO CITE"])) == {lora, retrieval}
    listed = (await ok(await auth_client.get(f"{API}/documents")))["items"]
    assert {t["name"] for d in listed for t in d["tags"]} == {"PEFT", "to cite"}

    clash = await auth_client.patch(f"{API}/tags/{tags['PEFT']['id']}", json={"name": "To Cite"})
    assert clash.status_code == 422 and "already have" in clash.json()["error"]["message"]

    # a tag removed from its last paper disappears
    await ok(await auth_client.put(f"{API}/documents/{lora}/tags", json={"names": ["to cite"]}))
    assert {t["name"] for t in await ok(await auth_client.get(f"{API}/tags"))} == {"to cite"}
    await ok(await auth_client.delete(f"{API}/tags/{tags['to cite']['id']}"), 204)
    assert (await ok(await auth_client.get(f"{API}/documents/{lora}/organization")))["tags"] == []

    too_many = await auth_client.put(
        f"{API}/documents/{lora}/tags", json={"names": [f"t{i}" for i in range(21)]}
    )
    assert too_many.status_code == 422


async def test_reading_status_and_paper_bookmarks(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    lora, retrieval = library["lora"], library["retrieval"]
    org = await ok(
        await auth_client.put(f"{API}/documents/{lora}/reading-status", json={"status": "reading"})
    )
    assert org["reading_status"] == "reading"
    assert await papers(auth_client, reading_status="reading") == [lora]
    assert await papers(auth_client, reading_status="none") == [retrieval]

    first = await ok(
        await auth_client.post(f"{API}/bookmarks", json={"document_id": retrieval}), 201
    )
    again = await ok(
        await auth_client.post(f"{API}/bookmarks", json={"document_id": retrieval}), 201
    )
    assert first["id"] == again["id"]  # idempotent
    assert await papers(auth_client, bookmarked=True) == [retrieval]
    assert await papers(auth_client, bookmarked=False) == [lora]
    detail = await ok(await auth_client.get(f"{API}/documents/{retrieval}"))
    assert detail["bookmarked"] is True

    await ok(await auth_client.delete(f"{API}/documents/{retrieval}/bookmark"), 204)
    assert await papers(auth_client, bookmarked=True) == []


async def test_passage_bookmarks_and_notes_are_anchored_and_go_with_the_paper(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    lora = library["lora"]
    target = {
        "page": 1,
        "char_start": 420,
        "quote": "rank-8 adapters",
        "boxes": [[1, 10, 20, 300, 40]],
    }
    passage = await ok(
        await auth_client.post(
            f"{API}/bookmarks",
            json={"document_id": lora, "kind": "passage", "target": target, "label": "Key result"},
        ),
        201,
    )
    assert passage["target"]["char_start"] == 420 and passage["document_title"].startswith(
        "Low-Rank"
    )
    await ok(await auth_client.post(f"{API}/bookmarks", json={"document_id": lora}), 201)
    kinds = [
        b["kind"]
        for b in await ok(await auth_client.get(f"{API}/bookmarks", params={"kind": "passage"}))
    ]
    assert kinds == ["passage"]

    note = await ok(
        await auth_client.post(
            f"{API}/notes",
            json={
                "document_id": lora,
                "content": "**Compare** with prefix tuning.",
                "anchor": {"type": "passage", **target},
            },
        ),
        201,
    )
    assert note["anchor"]["type"] == "passage" and note["anchor"]["quote"] == "rank-8 adapters"
    updated = await ok(
        await auth_client.patch(f"{API}/notes/{note['id']}", json={"content": "Edited"})
    )
    assert updated["content"] == "Edited" and updated["document_title"].startswith("Low-Rank")
    assert len(await ok(await auth_client.get(f"{API}/notes", params={"document_id": lora}))) == 1

    orphan = await auth_client.post(f"{API}/notes", json={"content": "Where does this go?"})
    assert orphan.status_code == 422

    await ok(await auth_client.delete(f"{API}/documents/{lora}"), 204)
    assert await ok(await auth_client.get(f"{API}/notes")) == []
    assert await ok(await auth_client.get(f"{API}/bookmarks")) == []


async def test_collection_notes_go_with_the_collection(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    review = await ok(await auth_client.post(f"{API}/collections", json={"name": "Review"}), 201)
    await ok(
        await auth_client.post(
            f"{API}/notes", json={"collection_id": review["id"], "content": "Scope: 2020+"}
        ),
        201,
    )
    listed = await ok(await auth_client.get(f"{API}/collections"))
    assert listed[0]["note_count"] == 1
    await ok(await auth_client.delete(f"{API}/collections/{review['id']}"), 204)
    assert await ok(await auth_client.get(f"{API}/notes")) == []


# --- filters affect retrieval and chat -----------------------------------------------------------


async def test_search_and_chat_can_be_limited_to_a_collection_or_tag(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    lora = library["lora"]
    peft = await ok(
        await auth_client.post(f"{API}/collections", json={"name": "PEFT", "document_ids": [lora]}),
        201,
    )
    await ok(await auth_client.put(f"{API}/documents/{lora}/tags", json={"names": ["adapters"]}))

    async def searched(filters: dict[str, Any]) -> set[str]:
        body = {"query": "retrieval and memory", "mode": "keyword", "filters": filters}
        result = await ok(await auth_client.post(f"{API}/search", json=body))
        return {r["document"]["id"] for r in result["results"]}

    assert await searched({}) == set(library.values())
    assert await searched({"collection_ids": [peft["id"]]}) == {lora}
    assert await searched({"tags": ["Adapters"]}) == {lora}

    facets = await ok(await auth_client.get(f"{API}/search/facets"))
    assert facets["collections"] == [{"value": peft["id"], "label": "PEFT", "count": 1}]
    assert facets["tags"] == [{"value": "adapters", "count": 1}]

    chat = await ok(
        await auth_client.post(f"{API}/chat/conversations", json={"collection_id": peft["id"]}), 201
    )
    assert chat["scope"] == "papers" and chat["document_ids"] == [lora]
    assert chat["collection_id"] == peft["id"]
    empty = await ok(await auth_client.post(f"{API}/collections", json={"name": "Empty"}), 201)
    response = await auth_client.post(
        f"{API}/chat/conversations", json={"collection_id": empty["id"]}
    )
    assert response.status_code == 422


# --- citation export -----------------------------------------------------------------------------


def test_bibtex_and_ris_use_only_known_metadata() -> None:
    refs = [
        Reference("Low-Rank Adapters for {Domain} Adaptation", ["Chen Wei", "Laura Martins"], 2023,
                  "arXiv", None, "2311.04567", keywords=["LoRA"]),
        Reference("Low-rank adapters, again & more", ["Wei, Chen"], 2023, "ACL", "10.1/xyz"),
        Reference("Untitled notes"),
    ]  # fmt: skip
    assert citation_keys(refs) == ["wei2023lowrank", "wei2023lowrankb", "anonuntitled"]
    text = bibtex(refs)
    assert "@misc{wei2023lowrank," in text and "eprint = {2311.04567}" in text
    assert r"title = {Low-Rank Adapters for \{Domain\} Adaptation}" in text
    assert "author = {Chen Wei and Laura Martins}" in text
    assert "@article{wei2023lowrankb," in text and "journal = {ACL}" in text
    assert r"again \& more" in text and "doi = {10.1/xyz}" in text
    assert "journal" not in text.split("@misc{anonuntitled")[1]

    records = ris(refs).split("ER  - ")
    assert "TY  - GEN" in records[0] and "UR  - https://arxiv.org/abs/2311.04567" in records[0]
    assert (
        "TY  - JOUR" in records[1] and "JO  - ACL" in records[1] and "DO  - 10.1/xyz" in records[1]
    )


async def test_collection_export_downloads(
    auth_client: AsyncClient, library: dict[str, str]
) -> None:
    collection = await ok(
        await auth_client.post(
            f"{API}/collections",
            json={"name": "My Thesis!", "document_ids": list(library.values())},
        ),
        201,
    )
    response = await auth_client.get(f"{API}/collections/{collection['id']}/export")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="my-thesis.bib"'
    assert response.text.count("@") == 2 and "2311.04567" in response.text
    ris_response = await auth_client.get(
        f"{API}/collections/{collection['id']}/export", params={"format": "ris"}
    )
    assert ris_response.text.count("TY  - ") == 2
