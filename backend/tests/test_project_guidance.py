"""Project guidance (what to do next), abbreviation-safe claim splitting, word-boundary titles."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.config import Settings
from app.demo import sample_papers as sp
from app.services.analysis.text import shorten
from app.services.projects.service import MIN_PAPERS, guidance
from app.services.rag.citations import split_claims
from tests.test_indexing_api import upload

API = "/api/v1"
NONE_DONE = dict.fromkeys(
    ("questions", "background", "gaps", "methods", "experiments", "outline"), False
)


def project(collection: bool = True) -> Any:
    return SimpleNamespace(collection_id="c" if collection else None)


def test_guidance_points_at_the_first_unfinished_step() -> None:
    assert guidance(project(), NONE_DONE, 5)["next_step"]["step"] == "questions"
    done = {**NONE_DONE, "questions": True, "background": True}
    assert guidance(project(), done, 5)["next_step"]["step"] == "gaps"
    everything = dict.fromkeys(NONE_DONE, True)
    finished = guidance(project(), everything, 5)["next_step"]
    assert finished["step"] is None and "export" in finished["message"]


def test_guidance_warns_when_there_are_too_few_papers_or_no_collection() -> None:
    assert guidance(project(), NONE_DONE, MIN_PAPERS)["notes"] == []
    few = guidance(project(), NONE_DONE, 2)["notes"]
    assert len(few) == 1 and "2 papers" in few[0] and "add 2 or more" in few[0]
    assert "1 paper." in guidance(project(), NONE_DONE, 1)["notes"][0]
    assert "Link a collection" in guidance(project(collection=False), NONE_DONE, None)["notes"][0]
    assert guidance(project(), NONE_DONE, None)["notes"] == []  # unknown size: no false alarm


def test_abbreviations_do_not_end_a_claim() -> None:
    text = "What is the impact of datasets such as Mr. TyDi and MKQA on retrieval? [2]"
    claims = split_claims(text)
    assert [c.text for c in claims] == [
        "What is the impact of datasets such as Mr. TyDi and MKQA on retrieval?"
    ]
    assert claims[0].citations == [2]
    # Real boundaries still split, including after "et al." and after a sentence ending in "No."
    assert (
        len(split_claims("Results by Wei et al. Showed gains on the benchmark. It cut memory."))
        == 3
    )
    assert len(split_claims("The retriever helps, e.g. Contriever. The reader does not.")) == 2


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("Short title", 80, "Short title"),
        (
            "Can retrieving only when needed, combined with a retriever trained without labels",
            78,
            "Can retrieving only when needed, combined with a retriever trained without…",
        ),
        (
            "SELF-RAG: LEARNING TO RETRIEVE, GENERATE, AND CRITIQUE",
            40,
            "SELF-RAG: LEARNING TO RETRIEVE…",
        ),
        ("Unbroken" * 20, 30, ("Unbroken" * 20)[:29] + "…"),
    ],
)
def test_shorten_cuts_at_a_word(text: str, limit: int, expected: str) -> None:
    result = shorten(text, limit)
    assert result == expected and len(result) <= limit


async def test_the_project_carries_guidance(
    auth_client: AsyncClient, settings: Settings, tmp_path: Path
) -> None:
    ids = []
    for key, paper in (("retrieval", sp.RETRIEVAL_PAPER), ("lora", sp.LORA_PAPER)):
        data = sp.write_sample_pdf(paper, tmp_path / f"{key}.pdf").read_bytes()
        ids.append(await upload(auth_client, settings, f"{key}.pdf", data))
    collection = (
        await auth_client.post(
            f"{API}/collections", json={"name": "Two papers", "document_ids": ids}
        )
    ).json()
    created = await auth_client.post(
        f"{API}/projects",
        json={
            "idea": "Adapt a retriever with low-rank adapters",
            "collection_id": collection["id"],
        },
    )
    assert created.status_code == 201, created.text
    guide = created.json()["guidance"]
    assert guide["next_step"]["step"] == "questions"
    assert any("2 papers" in note for note in guide["notes"])

    unlinked = (
        await auth_client.post(f"{API}/projects", json={"idea": "Adapt a retriever with adapters"})
    ).json()
    assert any("Link a collection" in note for note in unlinked["guidance"]["notes"])
