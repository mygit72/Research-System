"""The starter project's dataset loaders, checked against real sample rows from Hugging Face.

The rows in tests/fixtures/hf_rows were fetched from the datasets' own viewer API, so the
loaders are tested against the schemas the datasets really have. `datasets` itself isn't
installed here, so a stand-in module serves those rows.
"""

from __future__ import annotations

import csv
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.projects.starter import data
from tests.test_project_code import make_project, run, write_project

FIXTURES = Path(__file__).parent / "fixtures" / "hf_rows"
BY_ID = {
    "rajpurkar/squad": "squad",
    "microsoft/ms_marco": "ms_marco",
    "hotpotqa/hotpot_qa": "hotpot_qa",
    "mandarjoshi/trivia_qa": "trivia_qa",
    "google-research-datasets/nq_open": "nq_open",
}


def sample(key: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / f"{key}.json").read_text(encoding="utf-8"))["rows"]  # type: ignore[no-any-return]


class FakeDataset(list):  # type: ignore[type-arg]
    def shuffle(self, seed: int) -> FakeDataset:
        return FakeDataset(reversed(self))

    def select(self, indices: Any) -> FakeDataset:
        return FakeDataset(self[i] for i in indices)


@pytest.fixture
def hub(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str | None, str]]:
    """A stand-in `datasets` module; returns the (dataset, config, split) calls it received."""
    calls: list[tuple[str, str | None, str]] = []
    module = types.ModuleType("datasets")

    def load_dataset(name: str, config: str | None = None, split: str = "train") -> FakeDataset:
        calls.append((name, config, split))
        return FakeDataset(sample(BY_ID[name]))

    module.load_dataset = load_dataset  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "datasets", module)
    return calls


def test_ms_marco_ranks_the_candidates_and_marks_the_selected_ones(hub: list[Any]) -> None:
    rows = sample("ms_marco")
    examples = data.load("MS MARCO", limit=None)
    assert hub == [("microsoft/ms_marco", "v2.1", "validation")]
    kept = [r for r in rows if any(r["passages"]["is_selected"])]
    assert len(examples) == len(kept) > 0
    first, row = examples[0], kept[0]
    assert first["question"] == row["query"]
    assert first["passages"] == row["passages"]["passage_text"] and len(first["passages"]) == 10
    assert first["relevant"] == [i for i, f in enumerate(row["passages"]["is_selected"]) if f]
    assert all(a and a != data.NO_ANSWER for e in examples for a in e["answers"])


def test_hotpot_qa_marks_the_paragraphs_with_supporting_facts(hub: list[Any]) -> None:
    examples = data.load("HotpotQA")
    assert hub == [("hotpotqa/hotpot_qa", "distractor", "validation")]
    row = sample("hotpot_qa")[0]
    first = examples[0]
    assert first["answers"] == [row["answer"]] and len(first["passages"]) == len(
        row["context"]["title"]
    )
    relevant_titles = {row["context"]["title"][i] for i in first["relevant"]}
    assert (
        relevant_titles == set(row["supporting_facts"]["title"]) == {"Scott Derrickson", "Ed Wood"}
    )
    for i in first["relevant"]:
        assert first["passages"][i].startswith(row["context"]["title"][i] + ". ")


def test_trivia_qa_and_nq_open_have_answers_but_no_passages(hub: list[Any]) -> None:
    trivia = data.load("TriviaQA")
    assert hub[-1] == ("mandarjoshi/trivia_qa", "rc.nocontext", "validation")
    row = sample("trivia_qa")[0]
    assert trivia[0]["answers"][0] == row["answer"]["aliases"][0]
    assert len(trivia[0]["answers"]) == len(set(trivia[0]["answers"]))  # aliases deduplicated
    assert trivia[0]["passages"] == [] and trivia[0]["relevant"] == []

    nq = data.load("Natural Questions")
    assert hub[-1] == ("google-research-datasets/nq_open", "nq_open", "validation")
    assert nq[0]["answers"] == sample("nq_open")[0]["answer"] and nq[0]["passages"] == []


def test_squad_still_uses_its_context_as_the_one_relevant_passage(hub: list[Any]) -> None:
    first = data.load("SQuAD")[0]
    row = sample("squad")[0]
    assert first["passages"] == [row["context"]] and first["relevant"] == [0]
    assert first["answers"] == row["answers"]["text"]


def test_limit_shuffles_and_cuts(hub: list[Any]) -> None:
    assert len(data.load("TriviaQA", limit=2)) == 2
    assert [e["question"] for e in data.load("TriviaQA", limit=2)] == [
        r["question"] for r in reversed(sample("trivia_qa"))
    ][:2]


@pytest.mark.parametrize(
    ("name", "found"),
    [
        ("Natural Questions", True),
        ("NQ", True),
        ("nq-open", True),
        ("MS MARCO", True),
        ("ms_marco", True),
        ("MS-MARCO", True),
        ("Hotpot QA", True),
        ("hotpotqa", True),
        ("Trivia QA", True),
        ("SQuAD", True),
        ("toy", True),
        ("FEVER", False),
        ("BEIR", False),
    ],
)
def test_names_from_a_plan_find_their_loader(name: str, found: bool) -> None:
    assert (data.find_loader(name) is not None) is found


def test_a_dataset_without_a_loader_fails_loudly_and_points_somewhere_for_beir() -> None:
    with pytest.raises(NotImplementedError, match="load_fever") as fever:
        data.load("FEVER")
    assert "Where to look" not in str(fever.value)  # no pointer is better than an unchecked one
    with pytest.raises(NotImplementedError, match="beir-cellar"):
        data.load("BEIR")


async def run_plan(
    client: AsyncClient, tmp_path: Path, dataset: str, rows_module: Path
) -> list[dict[str, str]]:
    pid = await make_project(client, [dataset])
    files = (await client.get(f"/api/v1/projects/{pid}/code")).json()["files"]
    project = tmp_path / "project"
    project.mkdir()
    write_project(files, project)
    result = run(project, "run_experiments.py", "--only", "main-1", env_path=rows_module)
    assert result.returncode == 0, result.stderr
    return list(csv.DictReader((project / "results" / "results.csv").open(encoding="utf-8")))


@pytest.fixture
def shim(tmp_path: Path) -> Path:
    """A `datasets` module for the generated project's subprocess, serving the real sample rows."""
    folder = tmp_path / "shim"
    folder.mkdir()
    (folder / "datasets.py").write_text(
        f"""
import json
from pathlib import Path
IDS = {BY_ID!r}


class Rows(list):
    def shuffle(self, seed):
        return Rows(reversed(self))

    def select(self, indices):
        return Rows(self[i] for i in indices)


def load_dataset(name, config=None, split="train"):
    path = Path({str(FIXTURES)!r}) / (IDS[name] + ".json")
    return Rows(json.loads(path.read_text(encoding="utf-8"))["rows"])
""",
        encoding="utf-8",
    )
    return folder


async def test_a_dataset_without_passages_never_gets_a_retrieval_number(
    auth_client: AsyncClient, tmp_path: Path, shim: Path
) -> None:
    rows = await run_plan(auth_client, tmp_path, "TriviaQA", shim)
    sanity = [r for r in rows if r["system"] == "Lexical overlap (sanity check)"]
    assert {r["metric"] for r in sanity} == {"accuracy"} and all(
        r["status"] == "ok" for r in sanity
    )
    retrieval = [r for r in rows if r["metric"].startswith("recall@")]
    assert len(retrieval) == 3 and all(
        r["status"] == "todo" and r["value"] == "" for r in retrieval
    )
    assert all("no candidate passages" in r["note"] for r in retrieval)


async def test_a_dataset_with_candidates_gets_retrieval_numbers(
    auth_client: AsyncClient, tmp_path: Path, shim: Path
) -> None:
    rows = await run_plan(auth_client, tmp_path, "MS MARCO", shim)
    recall = [r for r in rows if r["metric"].startswith("recall@") and r["status"] == "ok"]
    assert {r["system"] for r in recall} == {
        "Lexical overlap (sanity check)",
        "Random (sanity check)",
    }
    assert all(0.0 <= float(r["value"]) <= 1.0 for r in recall)


async def test_without_the_datasets_package_the_run_says_what_to_install(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    rows = await run_plan(auth_client, tmp_path, "SQuAD", empty)
    todo = [r for r in rows if r["status"] == "todo" and r["system"] == "-"]
    assert todo and "datasets" in todo[0]["note"]
