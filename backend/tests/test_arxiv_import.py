"""arXiv import: strict id parsing, fixed hosts only, arXiv's own metadata kept through processing."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.errors import AppError, ValidationError
from app.demo import sample_papers as sp
from app.services import arxiv
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2310.11511v1</id>
    <published>2023-10-17T17:50:00Z</published>
    <title>Self-RAG:  Learning to Retrieve,
      Generate, and Critique</title>
    <summary>  A framework that retrieves
      on demand.  </summary>
    <author><name>Akari Asai</name></author>
    <author><name>Zeqiu Wu</name><arxiv:affiliation>UW</arxiv:affiliation></author>
    <arxiv:doi>10.48550/arXiv.2310.11511</arxiv:doi>
  </entry>
</feed>"""
NOT_FOUND = """<feed xmlns="http://www.w3.org/2005/Atom"><entry>
<id>http://arxiv.org/api/errors#incorrect_id_format</id><title>Error</title></entry></feed>"""


@pytest.fixture
def pdf(tmp_path: Path) -> bytes:
    return sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()


@pytest.fixture
def serve(monkeypatch: pytest.MonkeyPatch, pdf: bytes) -> list[str]:
    """Canned arXiv; returns the list of requested URLs."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text=NOT_FOUND if "0000.00000" in str(request.url) else ATOM)
        return httpx.Response(200, content=pdf)

    monkeypatch.setattr(
        arxiv, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2310.11511", ("2310.11511", None)),
        ("arXiv:2310.11511v2", ("2310.11511", "2")),
        ("https://arxiv.org/abs/2310.11511", ("2310.11511", None)),
        ("https://www.arxiv.org/pdf/2310.11511v3.pdf", ("2310.11511", "3")),
        ("  http://arxiv.org/abs/hep-th/9901001  ", ("hep-th/9901001", None)),
    ],
)
def test_references_are_parsed(text: str, expected: tuple[str, str | None]) -> None:
    assert arxiv.parse_reference(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "https://evil.example/abs/2310.11511",
        "https://arxiv.org.evil.example/abs/2310.11511",
        "http://169.254.169.254/latest/meta-data",
        "2310.11511; rm -rf /",
        "file:///etc/passwd",
        "not an id",
        "",
    ],
)
def test_anything_else_is_refused(text: str) -> None:
    with pytest.raises(ValidationError):
        arxiv.parse_reference(text)


async def test_import_keeps_arxivs_metadata_through_processing(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    response = await auth_client.post(
        f"{API}/documents/import", json={"refs": ["arXiv:2310.11511"]}
    )
    assert response.status_code == 201, response.text
    assert response.json()["errors"] == []
    document_id = response.json()["items"][0]["id"]
    await get_dispatcher(settings).drain()  # the parser runs now and must not overwrite it

    detail = (await auth_client.get(f"{API}/documents/{document_id}")).json()
    meta = detail["metadata"]
    assert detail["status"] == "ready"
    assert detail["title"] == "Self-RAG: Learning to Retrieve, Generate, and Critique"
    assert [a["name"] for a in meta["authors"]] == ["Akari Asai", "Zeqiu Wu"]
    assert meta["authors"][1]["affiliation"] == "UW"
    assert meta["abstract"] == "A framework that retrieves on demand."
    assert (meta["year"], meta["publication_date"]) == (2023, "2023-10-17")
    assert (meta["arxiv_id"], meta["doi"]) == ("2310.11511", "10.48550/arXiv.2310.11511")
    assert meta["provenance"]["authors"]["source"] == "arxiv"
    # Only the two fixed hosts were contacted, and the PDF was requested by id.
    assert serve == [
        "https://export.arxiv.org/api/query?id_list=2310.11511",
        "https://arxiv.org/pdf/2310.11511",
    ]


async def test_a_paper_already_in_the_library_is_not_fetched_twice(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    first = await auth_client.post(f"{API}/documents/import", json={"refs": ["2310.11511"]})
    assert first.status_code == 201
    await get_dispatcher(settings).drain()
    calls = len(serve)
    again = await auth_client.post(
        f"{API}/documents/import",
        json={"refs": ["https://arxiv.org/abs/2310.11511v2", "2310.11511"]},
    )
    assert again.status_code == 400
    errors = again.json()["error"]["details"]["errors"]
    assert len(errors) == 2 and all("already in your library" in e["message"] for e in errors)
    assert len(serve) == calls  # nothing was downloaded


async def test_each_paper_succeeds_or_fails_on_its_own(
    auth_client: AsyncClient, settings: Settings, serve: list[str]
) -> None:
    response = await auth_client.post(
        f"{API}/documents/import", json={"refs": ["2310.11511", "nonsense", "0000.00000"]}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert len(body["items"]) == 1
    assert {e["filename"] for e in body["errors"]} == {"nonsense", "0000.00000"}
    assert all(e["message"] for e in body["errors"])


async def test_local_only_mode_never_touches_the_network(
    auth_client: AsyncClient, settings: Settings, serve: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "local_only", True)
    response = await auth_client.post(f"{API}/documents/import", json={"refs": ["2310.11511"]})
    assert response.status_code == 400
    assert "turned off" in response.json()["error"]["message"] and serve == []


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(302, headers={"location": "https://evil.example/x.pdf"}),
        lambda r: httpx.Response(302, headers={"location": "http://arxiv.org/pdf/2310.11511"}),
        lambda r: httpx.Response(503),
    ],
    ids=["other-host", "downgrade-to-http", "server-error"],
)
async def test_redirects_elsewhere_and_failures_are_refused(
    handler: Callable[[httpx.Request], httpx.Response], settings: Settings
) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(AppError):
            await arxiv._get(client, "https://arxiv.org/pdf/2310.11511", 10_000)


async def test_oversized_and_non_pdf_answers_are_refused(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    def serve(body: bytes) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return (
                httpx.Response(200, text=ATOM)
                if request.url.host.startswith("export")
                else (httpx.Response(200, content=body))
            )

        monkeypatch.setattr(
            arxiv,
            "client_factory",
            lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

    serve(b"<html>not a pdf</html>")
    with pytest.raises(AppError, match="PDF"):
        await arxiv.fetch(settings, "2310.11511")
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)
    serve(b"%PDF" + b"0" * (2 * 1024 * 1024))
    with pytest.raises(ValidationError, match="larger"):
        await arxiv.fetch(settings, "2310.11511")
