"""The outline covers every project paper: nothing is left out silently, nothing is invented."""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.analysis.digests import Digest, Statement
from app.services.projects.generate import _best_statement
from app.workers.dispatcher import get_dispatcher
from tests.test_indexing_api import upload

API = "/api/v1"


async def ok(response: Any, code: int = 200) -> Any:
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture
async def papers(auth_client: AsyncClient, settings: Settings, tmp_path: Path) -> dict[str, str]:
    ids = {}
    for key, paper in (
        ("retrieval", sp.RETRIEVAL_PAPER),
        ("lora", sp.LORA_PAPER),
        ("rala", sp.RAG_ADAPTER_PAPER),
    ):
        data = sp.write_sample_pdf(paper, tmp_path / f"{key}.pdf").read_bytes()
        ids[key] = await upload(auth_client, settings, f"{key}.pdf", data)
    return ids


async def outline_of(client: AsyncClient, settings: Settings, pid: str) -> dict[str, Any]:
    await ok(await client.post(f"{API}/projects/{pid}/suggest/outline"), 202)
    await get_dispatcher(settings).drain()
    outline = (await ok(await client.get(f"{API}/projects/{pid}")))["steps"]["outline"]
    assert outline["status"] == "ready", outline["error"]
    return outline  # type: ignore[no-any-return]


async def test_a_paper_the_review_left_out_still_appears_in_the_outline(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, str]
) -> None:
    drain = get_dispatcher(settings).drain
    collection = await ok(
        await auth_client.post(
            f"{API}/collections",
            json={"name": "Two papers", "document_ids": [papers["retrieval"], papers["lora"]]},
        ),
        201,
    )
    project = await ok(
        await auth_client.post(
            f"{API}/projects",
            json={
                "idea": "Adapt retrieval-augmented generators",
                "collection_id": collection["id"],
            },
        ),
        201,
    )
    pid = project["id"]
    await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}", json={"question": "Does LoRA adapt the generator?"}
        )
    )
    await ok(await auth_client.post(f"{API}/projects/{pid}/reports/background"), 202)
    await drain()

    # A third paper joins after the review was written: the review's text can't mention it.
    await ok(
        await auth_client.post(
            f"{API}/collections/{collection['id']}/documents",
            json={"document_ids": [papers["rala"]]},
        )
    )
    rala_title = (await ok(await auth_client.get(f"{API}/documents/{papers['rala']}")))["title"]

    # No summary yet, so there is no checked statement to cite: it is named, honestly, not cited.
    outline = await outline_of(auth_client, settings, pid)
    related = next(s for s in outline["sections"] if s["key"] == "related_work")
    assert "Also in this project" in related["text"]
    line = next(x for x in related["text"].splitlines() if rala_title in x)
    assert "No statement from this paper passed the check" in line and "[" not in line

    # Once the paper has a checked summary, its contribution is cited, and BibTeX includes it.
    await ok(await auth_client.post(f"{API}/documents/{papers['rala']}/summary"), 202)
    await drain()
    outline = await outline_of(auth_client, settings, pid)
    related = next(s for s in outline["sections"] if s["key"] == "related_work")
    line = next(x for x in related["text"].splitlines() if rala_title in x)
    assert "No statement" not in line and "[" in line
    numbers = {int(n) for n in re.findall(r"\[(\d+)\]", line)}
    by_number = {s["number"]: s for s in outline["sources"]}
    assert numbers and all(by_number[n]["document"]["title"] == rala_title for n in numbers)
    assert numbers <= set(related["citations"])

    bundle = await auth_client.get(f"{API}/projects/{pid}/export", params={"format": "latex"})
    bib = zipfile.ZipFile(io.BytesIO(bundle.content)).read("references.bib").decode()
    assert rala_title.split(":")[0] in bib


async def test_every_project_paper_gets_passages_in_the_introduction(
    auth_client: AsyncClient, settings: Settings, papers: dict[str, str]
) -> None:
    collection = await ok(
        await auth_client.post(
            f"{API}/collections", json={"name": "All three", "document_ids": list(papers.values())}
        ),
        201,
    )
    project = await ok(
        await auth_client.post(
            f"{API}/projects",
            json={
                "idea": "Adapt retrieval-augmented generators",
                "collection_id": collection["id"],
            },
        ),
        201,
    )
    pid = project["id"]
    # A question that only one paper matches well: one search would return that paper alone.
    await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}",
            json={"question": "What is the exact match of low-rank adapters?"},
        )
    )
    outline = await outline_of(auth_client, settings, pid)
    titles = {s["document"]["title"] for s in outline["sources"]}
    expected = {
        (await ok(await auth_client.get(f"{API}/documents/{d}")))["title"] for d in papers.values()
    }
    intro = next(s for s in outline["sections"] if s["key"] == "introduction")
    intro_titles = {
        s["document"]["title"] for s in outline["sources"] if s["number"] in intro["citations"]
    }
    assert intro_titles <= titles <= expected
    assert titles == expected, "every paper in the project has a passage in the outline's sources"


def _digest(*statements: tuple[str, str, str]) -> Digest:
    import uuid

    digest = Digest(uuid.uuid4(), "Paper", 2024, "A. Author", uuid.uuid4())
    digest.statements = [Statement(f, t, s, [{"number": 1}]) for f, t, s in statements]
    return digest


def test_the_statement_cited_for_a_paper_is_its_best_checked_one() -> None:
    contribution_partial = ("contribution", "It adds X.", "partial")
    method_supported = ("method", "It trains with Y.", "supported")
    results_supported = ("results", "It scores Z.", "supported")
    # A fully supported statement beats a partly supported contribution…
    assert (
        _best_statement(_digest(contribution_partial, method_supported)).text == "It trains with Y."
    )
    # …contributions come before methods and results, other things being equal…
    both = ("contribution", "It adds X.", "supported")
    assert _best_statement(_digest(results_supported, method_supported, both)).text == "It adds X."
    # …a partly supported one is used when it is all there is, and nothing is invented otherwise.
    assert _best_statement(_digest(contribution_partial)).status == "partial"
    assert _best_statement(_digest(("limitations", "It fails.", "supported"))) is None
    assert _best_statement(_digest()) is None
