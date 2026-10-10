"""DOIs: strict recognition, Crossref metadata only, arXiv DOIs imported in full."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.core.errors import AppError, ValidationError
from app.demo import sample_papers as sp
from app.services import arxiv, doi
from app.workers.dispatcher import get_dispatcher

API = "/api/v1"
WORK = {
    "message": {
        "DOI": "10.1145/3292500.3330701",
        "title": ["Optuna: A Next-generation\n  Hyperparameter Optimization Framework"],
        "author": [
            {"given": "Takuya", "family": "Akiba", "affiliation": [{"name": "Preferred Networks"}]},
            {"given": "Shotaro", "family": "Sano", "affiliation": []},
            {"name": "The Optuna Team"},
        ],
        "abstract": "<jats:p><jats:title>Abstract</jats:title>The purpose of this study is\n"
        "to introduce <jats:italic>new</jats:italic> design criteria.</jats:p>",
        "issued": {"date-parts": [[2019, 7, 25]]},
        "container-title": ["Proceedings of the 25th ACM SIGKDD"],
    }
}


@pytest.fixture
def crossref(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "0000" in str(request.url):
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps(WORK).encode())

    monkeypatch.setattr(
        doi, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    return seen


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10.1145/3292500.3330701", "10.1145/3292500.3330701"),
        ("doi:10.1145/3292500.3330701", "10.1145/3292500.3330701"),
        ("https://doi.org/10.1145/3292500.3330701", "10.1145/3292500.3330701"),
        ("  http://dx.doi.org/10.1000/xyz(1)-2  ", "10.1000/xyz(1)-2"),
    ],
)
def test_dois_are_parsed(text: str, expected: str) -> None:
    assert doi.parse_doi(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "10.1145/../../etc/passwd?x=1",
        "10.1145/abc def",
        "10.1145/abc#frag",
        "https://evil.example/10.1145/abc",
        "http://169.254.169.254/latest",
        "2310.11511",
        "10.12/short-prefix",
        "",
    ],
)
def test_anything_else_is_not_a_doi(text: str) -> None:
    with pytest.raises(ValidationError):
        doi.parse_doi(text)


def test_references_are_routed_to_the_right_importer() -> None:
    assert doi.classify("10.48550/arXiv.2310.11511") == ("arxiv", "2310.11511")
    assert doi.classify("https://doi.org/10.48550/arXiv.2310.11511v2") == ("arxiv", "2310.11511v2")
    assert doi.classify("10.1145/3292500.3330701") == ("doi", "10.1145/3292500.3330701")
    assert doi.classify("arXiv:2310.11511") == ("arxiv", "arXiv:2310.11511")
    with pytest.raises(ValidationError, match="arXiv id, arXiv link or DOI"):
        doi.classify("what is this")


async def test_crossref_records_are_read_and_cleaned(
    crossref: list[str], settings: Settings
) -> None:
    record = await doi.fetch(settings, "https://doi.org/10.1145/3292500.3330701")
    assert crossref == ["https://api.crossref.org/works/10.1145/3292500.3330701"]
    assert record.title == "Optuna: A Next-generation Hyperparameter Optimization Framework"
    assert [a["name"] for a in record.authors] == [
        "Takuya Akiba",
        "Shotaro Sano",
        "The Optuna Team",
    ]
    assert record.authors[0]["affiliation"] == "Preferred Networks"
    assert record.abstract == "The purpose of this study is to introduce new design criteria."
    assert (record.year, record.published) == (2019, "2019-07-25")
    assert record.venue == "Proceedings of the 25th ACM SIGKDD"


async def test_partial_dates_and_missing_records(settings: Settings) -> None:
    year_only = json.dumps({"message": {"title": ["T"], "issued": {"date-parts": [[2020]]}}})
    record = doi.parse_work(year_only.encode(), "10.1/x")
    assert (record.year, record.published) == (2020, "2020")
    with pytest.raises(AppError):
        doi.parse_work(b"not json", "10.1/x")


async def test_unknown_dois_and_local_only_are_refused(
    crossref: list[str], settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError, match="no record"):
        await doi.fetch(settings, "10.0000/missing")
    crossref.clear()
    monkeypatch.setattr(settings, "local_only", True)
    with pytest.raises(AppError, match="turned off"):
        await doi.fetch(settings, "10.1145/3292500.3330701")
    assert crossref == []


async def test_a_non_arxiv_doi_explains_there_is_no_pdf_to_fetch(
    auth_client: AsyncClient, crossref: list[str]
) -> None:
    response = await auth_client.post(
        f"{API}/documents/import", json={"refs": ["10.1145/3292500.3330701"]}
    )
    assert response.status_code == 400, response.text
    error = response.json()["error"]
    assert "Optuna" in error["message"] and "can't be downloaded" in error["message"]
    assert "Fill from DOI" in error["hint"]


async def test_an_arxiv_doi_imports_the_paper_in_full(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    atom = (
        '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2310.11511v1</id>'
        "<published>2023-10-17T00:00:00Z</published><title>Self-RAG</title><summary>S.</summary>"
        "<author><name>Akari Asai</name></author></entry></feed>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "export.arxiv.org":
            return httpx.Response(200, text=atom)
        return httpx.Response(200, content=pdf)

    monkeypatch.setattr(
        arxiv, "client_factory", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    response = await auth_client.post(
        f"{API}/documents/import", json={"refs": ["https://doi.org/10.48550/arXiv.2310.11511"]}
    )
    assert response.status_code == 201, response.text
    document_id = response.json()["items"][0]["id"]
    await get_dispatcher(settings).drain()
    meta = (await auth_client.get(f"{API}/documents/{document_id}")).json()["metadata"]
    assert meta["arxiv_id"] == "2310.11511" and meta["authors"][0]["name"] == "Akari Asai"


async def test_a_papers_metadata_can_be_filled_from_its_doi(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path, crossref: list[str]
) -> None:
    pdf = sp.write_sample_pdf(sp.RETRIEVAL_PAPER, tmp_path / "r.pdf").read_bytes()
    uploaded = await auth_client.post(
        f"{API}/documents", files=[("files", ("r.pdf", pdf, "application/pdf"))]
    )
    document_id = uploaded.json()["items"][0]["id"]
    await get_dispatcher(settings).drain()

    response = await auth_client.post(
        f"{API}/documents/{document_id}/metadata/doi", json={"doi": "doi:10.1145/3292500.3330701"}
    )
    assert response.status_code == 200, response.text
    await get_dispatcher(settings).drain()
    detail = (await auth_client.get(f"{API}/documents/{document_id}")).json()
    meta = detail["metadata"]
    assert detail["title"].startswith("Optuna")
    assert meta["doi"] == "10.1145/3292500.3330701" and meta["year"] == 2019
    assert meta["venue"] == "Proceedings of the 25th ACM SIGKDD"
    assert meta["provenance"]["authors"]["source"] == "crossref"
    assert [a["name"] for a in meta["authors"]][:2] == ["Takuya Akiba", "Shotaro Sano"]

    # Reprocessing must not overwrite what Crossref gave.
    assert (await auth_client.post(f"{API}/documents/{document_id}/process")).status_code == 200
    await get_dispatcher(settings).drain()
    again = (await auth_client.get(f"{API}/documents/{document_id}")).json()["metadata"]
    assert again["doi"] == "10.1145/3292500.3330701" and again["year"] == 2019

    bad = await auth_client.post(
        f"{API}/documents/{document_id}/metadata/doi", json={"doi": "nope-not-a-doi"}
    )
    assert bad.status_code == 422


def test_shapes_seen_from_the_real_crossref_api() -> None:
    """Found by a live lookup: a subtitle kept apart from the title, an HTML-escaped venue."""
    payload = json.dumps(
        {
            "message": {
                "DOI": "10.1145/3292500.3330701",
                "title": ["Optuna"],
                "subtitle": ["A Next-generation Hyperparameter Optimization Framework"],
                "container-title": ["Proceedings of the 25th ACM SIGKDD &amp; Data Mining"],
                "author": [{"given": "Zo&#235;", "family": "Smith"}],
                "issued": {"date-parts": [[2019, 7, 25]]},
            }
        }
    ).encode()
    record = doi.parse_work(payload, "10.1145/3292500.3330701")
    assert record.title == "Optuna: A Next-generation Hyperparameter Optimization Framework"
    assert record.venue == "Proceedings of the 25th ACM SIGKDD & Data Mining"
    assert record.authors[0]["name"] == "Zoë Smith"

    already = {"message": {"title": ["Deep learning: an overview"], "subtitle": ["An Overview"]}}
    assert (
        doi.parse_work(json.dumps(already).encode(), "10.1/x").title == "Deep learning: an overview"
    )
    question = {"message": {"title": ["Is it?"], "subtitle": ["A study"]}}
    assert doi.parse_work(json.dumps(question).encode(), "10.1/x").title == "Is it? A study"
