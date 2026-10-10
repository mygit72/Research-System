"""Importing a folder of papers as a .zip, including hostile archives."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services import zip_import
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"


def make_zip(entries: dict[str, bytes], *, encrypted: tuple[str, ...] = ()) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    raw = bytearray(buffer.getvalue())
    for name in encrypted:  # zipfile clears the flag when writing, so set it in the directory
        at = raw.index(b"PK" + b"", 0)
        while at != -1:
            length = int.from_bytes(raw[at + 28 : at + 30], "little")
            if bytes(raw[at + 46 : at + 46 + length]) == name.encode():
                raw[at + 8] |= 0x01
            at = raw.find(b"PK", at + 4)
    return bytes(raw)


@pytest.fixture
def pdfs(tmp_path: Path) -> dict[str, bytes]:
    return {
        "retrieval": sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes(),
        "lora": sp.write_sample_pdf(sp.LORA_PAPER, tmp_path / "l.pdf").read_bytes(),
        "md": sp.write_sample_markdown(sp.RAG_ADAPTER_PAPER, tmp_path / "a.md").read_bytes(),
    }


async def post(client: AsyncClient, archive: bytes, **params: str):  # type: ignore[no-untyped-def]
    return await client.post(
        f"{API}/documents/import/zip",
        params=params,
        files={"file": ("papers.zip", archive, "application/zip")},
    )


async def test_a_folder_of_papers_is_imported_and_the_rest_explained(
    auth_client: AsyncClient, settings: Settings, pdfs: dict[str, bytes]
) -> None:
    archive = make_zip(
        {
            "thesis/papers/retrieval.pdf": pdfs["retrieval"],
            "thesis/papers/lora.pdf": pdfs["lora"],
            "thesis/notes/adapter.md": pdfs["md"],
            "thesis/": b"",
            "__MACOSX/thesis/._retrieval.pdf": b"junk",
            "thesis/.DS_Store": b"junk",
            "thesis/figure.png": b"\x89PNG",
            "thesis/more.zip": b"PK\x03\x04",
            "thesis/broken.pdf": b"this is not a pdf",
        }
    )
    response = await post(auth_client, archive, collection_name="Thesis reading")
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["items"]) == 3
    assert [e["filename"] for e in body["errors"]] == ["broken.pdf"]  # failed its own checks
    assert body["errors"][0]["message"]
    skipped = {s["filename"]: s["reason"] for s in body["skipped"]}
    assert set(skipped) == {"figure.png", "more.zip"}  # litter (.DS_Store, __MACOSX) isn't reported
    assert "supported file type" in skipped["figure.png"]
    assert "Archives inside archives" in skipped["more.zip"]

    await get_dispatcher(settings).drain()
    library = (await auth_client.get(f"{API}/documents")).json()["items"]
    assert len(library) == 3 and {d["status"] for d in library} == {"ready"}
    collection = (await auth_client.get(f"{API}/collections/{body['collection_id']}")).json()
    assert collection["name"] == "Thesis reading" and collection["paper_count"] == 3


async def test_entry_names_are_only_labels_never_paths(
    auth_client: AsyncClient, settings: Settings, pdfs: dict[str, bytes], tmp_path: Path
) -> None:
    archive = make_zip({"../../escape.pdf": pdfs["retrieval"], "C:\\evil\\win.pdf": pdfs["lora"]})
    response = await post(auth_client, archive)
    assert response.status_code == 201, response.text
    await get_dispatcher(settings).drain()
    names = {
        d["original_filename"] for d in (await auth_client.get(f"{API}/documents")).json()["items"]
    }
    assert names == {"escape.pdf", "win.pdf"}
    assert not list(tmp_path.parent.rglob("escape.pdf")) and not list(tmp_path.rglob("win.pdf"))[1:]


async def test_hostile_archives_are_refused_or_skipped(
    auth_client: AsyncClient, pdfs: dict[str, bytes]
) -> None:
    bomb = make_zip({"bomb.txt": b"0" * (6 * 1024 * 1024), "ok.pdf": pdfs["retrieval"]})
    response = await post(auth_client, bomb)
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert body["skipped"] == [
        {"filename": "bomb.txt", "reason": "Expands suspiciously much when unpacked."}
    ]

    locked = make_zip(
        {"secret.pdf": pdfs["lora"], "ok.pdf": pdfs["retrieval"]}, encrypted=("secret.pdf",)
    )
    body = (await post(auth_client, locked)).json()
    assert {s["filename"]: s["reason"] for s in body["skipped"]} == {
        "secret.pdf": "Password-protected."
    }

    many = make_zip({f"p{i}.txt": b"A short note about retrieval." * 5 for i in range(101)})
    response = await post(auth_client, many)
    assert response.status_code == 422 and "101 papers" in response.json()["error"]["message"]


async def test_not_a_zip_and_empty_zips_say_what_to_do(auth_client: AsyncClient) -> None:
    response = await post(auth_client, b"definitely not a zip")
    assert response.status_code == 422 and "valid zip" in response.json()["error"]["message"]
    empty = await post(auth_client, make_zip({"image.png": b"\x89PNG", "dir/": b""}))
    assert empty.status_code == 422
    assert "No papers were found" in empty.json()["error"]["message"]


async def test_the_archive_itself_has_a_size_limit(
    auth_client: AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_zip_size_mb", 1)
    response = await post(auth_client, b"PK" + bytes(2 * 1024 * 1024))
    assert response.status_code == 422
    assert "1 MB limit" in response.json()["error"]["message"]


def test_read_entry_counts_the_bytes_it_really_reads() -> None:
    archive = zipfile.ZipFile(io.BytesIO(make_zip({"a.txt": b"x" * 5000, "b.txt": b"y" * 5000})))
    a, b = archive.infolist()
    ok = zip_import.read_entry(archive, a, 10_000, zip_import.Budget(100_000))
    assert not isinstance(ok, str) and ok.read() == b"x" * 5000
    assert zip_import.read_entry(archive, a, 1000, zip_import.Budget(100_000)) == (
        "Larger than the 0 MB limit."
    )
    budget = zip_import.Budget(7000)
    first = zip_import.read_entry(archive, a, 10_000, budget)
    assert not isinstance(first, str) and budget.left == 2000
    assert (
        zip_import.read_entry(archive, b, 10_000, budget)
        == "The archive is too large to unpack in full."
    )


def test_display_names_take_the_last_segment_whatever_the_separator() -> None:
    assert zip_import.display_name("a/b/c.pdf") == "c.pdf"
    assert zip_import.display_name("..\\..\\x.pdf") == "x.pdf"
