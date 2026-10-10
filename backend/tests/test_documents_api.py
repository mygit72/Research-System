"""End-to-end document flow through the HTTP API with inline background jobs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.workers.dispatcher import get_dispatcher
from tests.conftest import register

PDF = "application/pdf"


@pytest.fixture
def paper_pdf(tmp_path: Path) -> bytes:
    return sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "paper.pdf").read_bytes()


async def upload(
    client: AsyncClient, settings: Settings, *files: tuple[str, bytes, str]
) -> dict[str, Any]:
    response = await client.post("/api/v1/documents", files=[("files", f) for f in files])
    await get_dispatcher(settings).drain()
    return {"status": response.status_code, **response.json()}


async def test_upload_process_and_read_back(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes
) -> None:
    result = await upload(auth_client, settings, ("paper.pdf", paper_pdf, PDF))
    assert result["status"] == 201
    assert result["errors"] == []
    doc_id = result["items"][0]["id"]
    assert result["items"][0]["status"] == "queued"

    detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert detail["status"] == "ready", detail
    assert detail["title"] == sp.RETRIEVAL_PAPER.title
    assert detail["authors_display"] == "Maya Lindqvist, Tomas Okafor, Priya Raman"
    assert detail["year"] == 2024 and detail["page_count"] == 2
    assert detail["metadata"]["arxiv_id"] == "2403.01234"
    assert detail["version"]["processing_config"]["stats"]["tables"] == 1
    assert detail["version"]["used_ocr"] is False
    assert detail["processing"] is None

    job = (await auth_client.get("/api/v1/jobs")).json()["items"][0]
    assert job["status"] == "succeeded" and job["progress"] == 1.0

    structure = (await auth_client.get(f"/api/v1/documents/{doc_id}/structure")).json()
    titles = [s["title"] for s in structure["sections"]]
    assert "Training Objective" in titles
    child = next(s for s in structure["sections"] if s["title"] == "Training Objective")
    parent = next(s for s in structure["sections"] if s["id"] == child["parent_id"])
    assert parent["title"] == "Method"
    assert {e["label"] for e in structure["elements"]} >= {"Table 1", "Figure 1", "Equation 1"}
    assert len(structure["references"]) == 4
    assert len(structure["pages"]) == 2


async def test_signed_assets(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, paper_pdf: bytes
) -> None:
    result = await upload(auth_client, settings, ("paper.pdf", paper_pdf, PDF))
    detail = (await auth_client.get(f"/api/v1/documents/{result['items'][0]['id']}")).json()
    assets = detail["assets"]

    thumb = await client.get(assets["thumbnail"], headers={"Authorization": ""})
    assert thumb.status_code == 200 and thumb.content.startswith(b"\x89PNG")

    page_url = assets["page_template"].replace("{page}", "2").replace("{width}", "800")
    page = await client.get(page_url)
    assert page.status_code == 200 and page.headers["content-type"] == "image/png"
    missing = await client.get(
        assets["page_template"].replace("{page}", "9").replace("{width}", "800")
    )
    assert missing.status_code == 404

    original = await client.get(assets["file"])
    assert original.content == paper_pdf
    assert original.headers["content-disposition"].startswith("inline")

    tampered = assets["file"].replace("sig=", "sig=x")
    assert (await client.get(tampered)).status_code == 403


async def test_multi_upload_partial_failure(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    md = sp.write_sample_markdown(sp.LORA_PAPER, tmp_path / "lora.md").read_bytes()
    result = await upload(
        auth_client,
        settings,
        ("lora.md", md, "text/markdown"),
        ("fake.pdf", b"PK\x03\x04not a pdf", PDF),
        ("script.exe", b"MZ", "application/octet-stream"),
    )
    assert result["status"] == 201
    assert len(result["items"]) == 1
    assert [e["filename"] for e in result["errors"]] == ["fake.pdf", "script.exe"]
    assert "valid PDF" in result["errors"][0]["message"]


async def test_all_invalid_upload_is_an_error(auth_client: AsyncClient, settings: Settings) -> None:
    result = await upload(auth_client, settings, ("x.exe", b"MZ", "application/octet-stream"))
    assert result["status"] == 400
    assert "supported file type" in result["error"]["message"]


async def test_upload_size_limit(auth_client: AsyncClient, settings: Settings) -> None:
    settings.max_upload_size_mb = 1
    big = b"word " * (300 * 1024)
    result = await upload(auth_client, settings, ("big.txt", big, "text/plain"))
    assert result["status"] == 400
    assert "1 MB limit" in result["error"]["message"]


async def test_failed_processing_is_explained_and_retryable(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    scanned = sp.write_scanned_pdf(tmp_path / "scan.pdf").read_bytes()
    result = await upload(auth_client, settings, ("scan.pdf", scanned, PDF))
    doc_id = result["items"][0]["id"]
    detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert detail["status"] == "failed"
    assert "scanned" in detail["error_message"]
    assert "Traceback" not in str(detail)

    retried = await auth_client.post(f"/api/v1/documents/{doc_id}/process")
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    await get_dispatcher(settings).drain()
    again = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert again["status"] == "failed"


async def test_duplicates_and_resolution(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes, tmp_path: Path
) -> None:
    first = (await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF)))["items"][0]["id"]
    exact = (await upload(auth_client, settings, ("copy.pdf", paper_pdf, PDF)))["items"][0]
    assert exact["duplicate_kind"] == "exact_duplicate"
    assert exact["duplicate_of_id"] == first

    # Same paper as HTML → same title → probable duplicate (never auto-rejected).
    html = sp.write_sample_html(sp.RETRIEVAL_PAPER, tmp_path / "p.html").read_bytes()
    probable_id = (await upload(auth_client, settings, ("p.html", html, "text/html")))["items"][0][
        "id"
    ]
    probable = (await auth_client.get(f"/api/v1/documents/{probable_id}")).json()
    assert probable["duplicate_kind"] == "probable_duplicate"
    assert probable["duplicate_of"]["title"] == sp.RETRIEVAL_PAPER.title

    kept = await auth_client.post(
        f"/api/v1/documents/{exact['id']}/duplicate-resolution", json={"action": "keep_both"}
    )
    assert kept.json()["duplicate_kind"] is None

    merged = await auth_client.post(
        f"/api/v1/documents/{probable_id}/duplicate-resolution", json={"action": "merge_as_version"}
    )
    assert merged.status_code == 200 and merged.json()["id"] == first
    versions = (await auth_client.get(f"/api/v1/documents/{first}/versions")).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert (await auth_client.get(f"/api/v1/documents/{probable_id}")).status_code == 404
    stats = (await auth_client.get("/api/v1/documents/stats")).json()
    assert stats["total"] == 2 and stats["duplicates"] == 0


async def test_new_version_upload(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes, tmp_path: Path
) -> None:
    doc_id = (await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF)))["items"][0]["id"]
    same = await auth_client.post(
        f"/api/v1/documents/{doc_id}/versions", files={"file": ("a.pdf", paper_pdf, PDF)}
    )
    assert same.status_code == 409

    revised = sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "v2.pdf").read_bytes()
    response = await auth_client.post(
        f"/api/v1/documents/{doc_id}/versions", files={"file": ("v2.pdf", revised, PDF)}
    )
    assert response.status_code == 201
    await get_dispatcher(settings).drain()
    detail = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert detail["version"]["version_number"] == 2
    assert detail["version_count"] == 2
    assert detail["title"] == sp.LORA_PAPER.title


async def test_metadata_correction_survives_reprocessing(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes
) -> None:
    doc_id = (await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF)))["items"][0]["id"]
    patched = await auth_client.patch(
        f"/api/v1/documents/{doc_id}/metadata",
        json={
            "venue": "SIGIR 2024",
            "authors": [{"name": "M. Lindqvist"}],
            "doi": "https://doi.org/10.1/xyz",
        },
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["metadata"]["doi"] == "10.1/xyz"
    assert body["authors_display"] == "M. Lindqvist"
    assert body["metadata"]["provenance"]["venue"]["source"] == "user"

    bad = await auth_client.patch(f"/api/v1/documents/{doc_id}/metadata", json={"doi": "nope"})
    assert bad.status_code == 422

    await auth_client.post(f"/api/v1/documents/{doc_id}/process")
    await get_dispatcher(settings).drain()
    after = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert after["metadata"]["venue"] == "SIGIR 2024"
    assert after["metadata"]["authors"] == [
        {"name": "M. Lindqvist", "affiliation": None, "email": None}
    ]
    assert after["metadata"]["arxiv_id"] == "2403.01234"  # uncorrected fields are refreshed


async def test_listing_search_sort_and_delete(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes, tmp_path: Path
) -> None:
    md = sp.write_sample_markdown(sp.LORA_PAPER, tmp_path / "l.md").read_bytes()
    await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF), ("l.md", md, "text/markdown"))

    listing = (await auth_client.get("/api/v1/documents?sort=title")).json()
    assert [d["title"][:5] for d in listing["items"]] == ["Hybri", "Low-R"]
    assert listing["total"] == 2
    found = (await auth_client.get("/api/v1/documents", params={"q": "chen wei"})).json()
    assert [d["title"] for d in found["items"]] == [sp.LORA_PAPER.title]

    doc = listing["items"][0]
    file_path = Path(settings.storage_dir)
    assert any(file_path.rglob("*.pdf"))
    assert (await auth_client.delete(f"/api/v1/documents/{doc['id']}")).status_code == 204
    assert (await auth_client.get(f"/api/v1/documents/{doc['id']}")).status_code == 404
    assert not any((file_path / "documents").rglob("*.pdf")), "stored file removed after commit"


async def test_documents_are_private(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, paper_pdf: bytes
) -> None:
    doc_id = (await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF)))["items"][0]["id"]
    other = await register(client)
    headers = {"Authorization": f"Bearer {other['access_token']}"}
    for method, path in [
        ("GET", f"/api/v1/documents/{doc_id}"),
        ("GET", f"/api/v1/documents/{doc_id}/structure"),
        ("PATCH", f"/api/v1/documents/{doc_id}/metadata"),
        ("DELETE", f"/api/v1/documents/{doc_id}"),
    ]:
        response = await client.request(method, path, headers=headers, json={"venue": "x"})
        assert response.status_code == 404, (method, path)
    assert (await client.get("/api/v1/documents", headers=headers)).json()["total"] == 0


async def test_timestamps_are_utc_aware(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes
) -> None:
    doc = (await upload(auth_client, settings, ("a.pdf", paper_pdf, PDF)))["items"][0]
    assert doc["created_at"].endswith(("Z", "+00:00"))
    me = (await auth_client.get("/api/v1/users/me")).json()
    assert me["created_at"].endswith(("Z", "+00:00"))


async def test_newer_upload_is_flagged_regardless_of_processing_order(
    auth_client: AsyncClient, settings: Settings, paper_pdf: bytes, tmp_path: Path
) -> None:
    """Upload A then B, but let B finish processing first: B is still the duplicate."""
    md = sp.write_sample_markdown(sp.RETRIEVAL_PAPER, tmp_path / "p.md").read_bytes()
    dispatcher = get_dispatcher(settings)
    first = await auth_client.post(
        "/api/v1/documents", files=[("files", ("a.pdf", paper_pdf, PDF))]
    )
    await dispatcher.drain()
    first_id = first.json()["items"][0]["id"]
    # Simulate "A hasn't finished yet": reprocess A after B is uploaded and processed.
    second = await auth_client.post(
        "/api/v1/documents", files=[("files", ("b.md", md, "text/markdown"))]
    )
    second_id = second.json()["items"][0]["id"]
    await dispatcher.drain()
    await auth_client.post(f"/api/v1/documents/{first_id}/process")
    await dispatcher.drain()

    a = (await auth_client.get(f"/api/v1/documents/{first_id}")).json()
    b = (await auth_client.get(f"/api/v1/documents/{second_id}")).json()
    assert a["duplicate_kind"] is None
    assert b["duplicate_kind"] == "probable_duplicate" and b["duplicate_of_id"] == first_id


def test_every_response_datetime_is_sent_as_utc() -> None:
    """SQLite returns naive datetimes; a response schema that doesn't mark them UTC makes
    browsers read them as local time (a paper's "time remaining" was off by the UTC offset)."""
    import importlib
    import pkgutil

    from pydantic import BaseModel

    import app.schemas as schemas
    from app.schemas.common import APIModel

    requests = {"ExperimentPlanRequest"}  # input, not output
    offenders = []
    for module in pkgutil.iter_modules(schemas.__path__):
        mod = importlib.import_module(f"app.schemas.{module.name}")
        for name, obj in vars(mod).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj.__module__ == mod.__name__
                and not issubclass(obj, APIModel)
                and name not in requests | {"TokenResponse"}  # built from aware datetimes
                and any("datetime" in str(f.annotation) for f in obj.model_fields.values())
            ):
                offenders.append(f"{mod.__name__}.{name}")
    assert offenders == []
