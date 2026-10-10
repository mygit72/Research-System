"""Research Project Builder: idea → questions → background → gap → methods → plan → outline."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime, timedelta
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


async def test_a_project_from_idea_to_outline(
    auth_client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    drain = get_dispatcher(settings).drain
    collection = await ok(
        await auth_client.post(
            f"{API}/collections",
            json={"name": "RAG thesis", "document_ids": list(library.values())},
        ),
        201,
    )
    project = await ok(
        await auth_client.post(
            f"{API}/projects",
            json={
                "idea": "Adapt retrieval-augmented generators to their retriever with low-rank "
                "adapters. Does it improve exact match?",
                "collection_id": collection["id"],
            },
        ),
        201,
    )
    pid = project["id"]
    assert project["title"].startswith("Adapt retrieval-augmented generators")
    assert project["completion"] == dict.fromkeys(
        ("questions", "background", "gaps", "methods", "experiments", "outline"), False
    )

    # 1. Questions: suggested from passages, each citing what it builds on.
    started = await ok(await auth_client.post(f"{API}/projects/{pid}/suggest/questions"), 202)
    assert started["steps"]["questions"]["status"] == "running"
    await drain()
    project = await ok(await auth_client.get(f"{API}/projects/{pid}"))
    questions = project["steps"]["questions"]
    assert questions["status"] == "ready" and questions["suggestions"]
    numbers = {s["number"] for s in questions["sources"]}
    for suggestion in questions["suggestions"]:
        assert suggestion["citations"] and set(suggestion["citations"]) <= numbers
        assert suggestion["papers"]
    await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}",
            json={"question": "Does adapting the generator with LoRA improve exact match?"},
        )
    )

    # 2. Background: a literature review of the collection, linked to the project.
    started = await ok(await auth_client.post(f"{API}/projects/{pid}/reports/background"), 202)
    assert started["reports"]["background"]["kind"] == "review"
    await drain()
    project = await ok(await auth_client.get(f"{API}/projects/{pid}"))
    assert project["reports"]["background"]["status"] == "ready"
    assert project["completion"]["background"] is True

    # 3. Gap and hypothesis.
    await ok(await auth_client.post(f"{API}/projects/{pid}/reports/gaps"), 202)
    await drain()
    project = await ok(await auth_client.get(f"{API}/projects/{pid}"))
    gaps_report = await ok(
        await auth_client.get(f"{API}/reports/{project['reports']['gaps']['id']}")
    )
    gap = gaps_report["sections"][0]["data"]["gaps"][0]
    project = await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}",
            json={
                "gap": {
                    "id": gap["id"],
                    "title": gap["title"],
                    "text": gap["text"],
                    "origin": gap["origin"],
                },
                "hypothesis": "LoRA-adapting the generator to its retriever raises exact match.",
            },
        )
    )
    assert project["completion"]["gaps"] is True

    # 4. Methods: what the project's papers actually use, with the papers.
    project = await ok(await auth_client.post(f"{API}/projects/{pid}/methods"))
    suggestions = project["steps"]["methods"]["suggestions"]
    sciqa = next(d for d in suggestions["dataset"] if d["name"] == "SciQA-2400")
    assert sciqa["count"] == 3 and len(sciqa["papers"]) == 3
    assert any(m["name"] == "LoRA" for m in suggestions["method"])
    project = await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}",
            json={
                "methods": {
                    "datasets": ["SciQA-2400", "Natural Questions"],
                    "baselines": ["Full fine-tuning"],
                    "methods": ["LoRA"],
                    "metrics": ["Exact match"],
                }
            },
        )
    )
    assert project["completion"]["methods"] is True

    # 5. Experiments and milestones.
    deadline = (datetime.now(UTC).date() + timedelta(days=90)).isoformat()
    project = await ok(
        await auth_client.post(f"{API}/projects/{pid}/experiments", json={"deadline": deadline})
    )
    items = project["steps"]["experiments"]["items"]
    assert [i["kind"] for i in items] == ["main", "main", "ablation", "analysis"]
    assert items[0]["setup"] == "LoRA vs. Full fine-tuning on SciQA-2400"
    assert "raises exact match" in items[0]["goal"]
    milestones = project["steps"]["experiments"]["milestones"]
    dues = [date.fromisoformat(m["due"]) for m in milestones]
    assert (
        len(milestones) == 6 and dues == sorted(dues) and dues[-1] == date.fromisoformat(deadline)
    )

    # 6. Outline: cited introduction, related work from the review, scaffolds from the plan.
    await ok(await auth_client.post(f"{API}/projects/{pid}/suggest/outline"), 202)
    await drain()
    project = await ok(await auth_client.get(f"{API}/projects/{pid}"))
    outline = project["steps"]["outline"]
    assert outline["status"] == "ready", outline["error"]
    sections = {s["key"]: s for s in outline["sections"]}
    assert list(sections) == ["introduction", "related_work", "method", "experiments", "conclusion"]
    sources = {s["number"] for s in outline["sources"]}
    assert set(sections["related_work"]["citations"]) <= sources
    assert sections["related_work"]["label"] == "From your literature review"
    assert "raises exact match" in sections["method"]["text"]
    assert sections["method"]["origin"] == "scaffold"
    assert "LoRA vs. Full fine-tuning on SciQA-2400" in sections["experiments"]["text"]
    assert all(project["completion"].values())

    edited = await ok(
        await auth_client.patch(
            f"{API}/projects/{pid}",
            json={"outline": [{"key": "conclusion", "text": "We find that it helps [1]."}]},
        )
    )
    conclusion = next(s for s in edited["steps"]["outline"]["sections"] if s["key"] == "conclusion")
    assert conclusion["edited"] is True

    # Exports: the plan, and the outline as LaTeX with BibTeX.
    md = await auth_client.get(f"{API}/projects/{pid}/export", params={"format": "md"})
    assert (
        md.status_code == 200 and "## Research question" in md.text and "## Milestones" in md.text
    )
    docx = await auth_client.get(f"{API}/projects/{pid}/export", params={"format": "docx"})
    assert docx.content[:2] == b"PK"
    latex = await auth_client.get(f"{API}/projects/{pid}/export", params={"format": "latex"})
    archive = zipfile.ZipFile(io.BytesIO(latex.content))
    tex = archive.read("main.tex").decode()
    bib = archive.read("references.bib").decode()
    assert "\\section{Related work}" in tex and "\\cite{" in tex
    assert "\\bibliography{references}" in tex and bib.startswith("@")


async def test_validation_and_privacy(
    auth_client: AsyncClient, client: AsyncClient, settings: Settings, library: dict[str, str]
) -> None:
    await ok(await auth_client.post(f"{API}/projects", json={"idea": "rag"}), 422)
    project = await ok(
        await auth_client.post(f"{API}/projects", json={"idea": "Hybrid retrieval for science QA"}),
        201,
    )
    pid = project["id"]
    await ok(await auth_client.post(f"{API}/projects/{pid}/suggest/outline"), 422)  # no question
    past = (datetime.now(UTC).date() - timedelta(days=1)).isoformat()
    await ok(
        await auth_client.post(f"{API}/projects/{pid}/experiments", json={"deadline": past}), 422
    )
    listed = await ok(await auth_client.get(f"{API}/projects"))
    assert [p["id"] for p in listed] == [pid]

    owner = auth_client.headers["Authorization"]  # the same client object as `client`
    other = await register(client)
    client.headers["Authorization"] = f"Bearer {other['access_token']}"
    await ok(await client.get(f"{API}/projects/{pid}"), 404)
    assert await ok(await client.get(f"{API}/projects")) == []
    client.headers["Authorization"] = owner
    await ok(await client.delete(f"{API}/projects/{pid}"), 204)
    await ok(await client.get(f"{API}/projects/{pid}"), 404)
