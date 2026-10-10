"""The starter project's finished components, and the systems generated from them."""

from __future__ import annotations

import csv
import math
import os
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.services.projects.starter import components as c
from app.services.projects.starter import data
from tests.test_project_code import make_project, run, write_project

API = "/api/v1"
MODEL_TESTS = pytest.mark.skipif(
    not os.environ.get("RUN_MODEL_TESTS"), reason="downloads models; set RUN_MODEL_TESTS=1"
)


def example(question: str, passages: list[str]) -> data.Example:
    return {"question": question, "passages": passages, "relevant": [0], "answers": []}


# --- by hand ------------------------------------------------------------------------------------


def test_bm25_matches_a_hand_calculation() -> None:
    passages = ["apple banana", "banana cherry", "cherry date"]
    scorer = c.BM25Scorer()
    scorer.prepare([example("x", passages)])
    # N=3, df(banana)=2: idf = ln(1 + (3-2+0.5)/(2+0.5)) = ln 1.6. Both banana passages have length
    # 2 = the average, so the length factor is 1 and tf=1 gives idf * (k1+1) / (1 + k1) = idf.
    scores = scorer.score(example("banana", passages))
    assert scores == pytest.approx([math.log(1.6), math.log(1.6), 0.0])


def test_bm25_prefers_rare_words_and_shorter_passages() -> None:
    passages = ["cat dog", "cat bird", "bird " + "filler " * 12, "fish"]
    scorer = c.BM25Scorer()
    scorer.prepare([example("x", passages)])
    rare = scorer.score(example("fish", passages))
    assert rare.index(max(rare)) == 3 and rare[:3] == [0.0, 0.0, 0.0]
    bird = scorer.score(example("bird", passages))
    assert bird[1] > bird[2] > 0.0  # the same word, in a short and in a long passage


def test_bm25_without_prepare_uses_the_examples_own_passages() -> None:
    ex = example("banana", ["apple banana", "cherry date"])
    assert c.BM25Scorer().score(ex)[0] > 0.0


def test_reciprocal_rank_fusion_by_hand() -> None:
    first, second = [3.0, 2.0, 1.0], [1.0, 2.0, 3.0]  # opposite orders
    fused = c.rrf([first, second], k=60)
    assert fused[0] == pytest.approx(1 / 61 + 1 / 63)
    assert fused[1] == pytest.approx(2 / 62)
    assert fused[2] == pytest.approx(1 / 61 + 1 / 63)
    assert c.order_of(fused) == [0, 2, 1]  # the two ends tie and keep their order; the middle loses
    # a passage that one list ranks first and the other ranks last beats one ranked middle twice
    assert fused[0] > fused[1]


def test_order_of_is_stable_on_ties() -> None:
    assert c.order_of([1.0, 3.0, 3.0, 2.0]) == [1, 2, 3, 0]


class Fixed:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores

    def score(self, example: data.Example) -> list[float]:
        return self.scores[: len(example["passages"])]


class ByLength:
    """A stand-in reranker: prefers longer passages."""

    def score(self, example: data.Example) -> list[float]:
        return [float(len(p)) for p in example["passages"]]


def test_a_pipeline_reranks_only_the_top_candidates() -> None:
    ex = example("q", ["aaaa", "b", "cc", "ddd", "eeeee"])
    first = Fixed([5.0, 4.0, 3.0, 2.0, 1.0])  # first-stage order 0,1,2,3,4
    assert c.Pipeline([first]).rank(ex) == [0, 1, 2, 3, 4]
    # depth 3: indices 0,1,2 reranked by length (aaaa, cc, b); 3 and 4 keep first-stage order
    assert c.Pipeline([first], ByLength(), depth=3).rank(ex) == [0, 2, 1, 3, 4]


def test_a_pipeline_fuses_several_first_stage_scorers() -> None:
    ex = example("q", ["a", "b", "c"])
    forward, backward = Fixed([3.0, 2.0, 1.0]), Fixed([1.0, 2.0, 3.0])
    assert c.Pipeline([forward, backward]).rank(ex) == [0, 2, 1]
    assert c.Pipeline([forward]).rank(ex) == [0, 1, 2]


def test_a_pipeline_copes_with_no_passages_and_no_scorers() -> None:
    assert c.Pipeline([Fixed([])]).rank(example("q", [])) == []
    with pytest.raises(ValueError, match="at least one"):
        c.Pipeline([])


def test_the_extractive_reader_only_ever_returns_text_from_the_passage() -> None:
    passage = "The sky is blue. Contrastive learning trains retrievers without labels. Cats sleep."
    answer = c.best_sentence("How are retrievers trained without labels?", passage)
    assert answer == "Contrastive learning trains retrievers without labels."
    assert answer in passage
    assert c.best_sentence("anything", "one sentence without a full stop") == (
        "one sentence without a full stop"
    )


# --- plan names ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("names", "stages", "rerank", "generate", "unmapped"),
    [
        (["BM25"], ["bm25"], False, False, []),
        (["DPR"], ["dpr"], False, False, []),
        (["Dense Passage Retrieval"], ["dpr"], False, False, []),
        (["Contrastive learning"], ["contriever"], False, False, []),
        (["Hybrid retrieval"], ["bm25", "sentence"], False, False, []),
        (["Reranking"], ["bm25"], True, False, []),  # a reranker needs candidates
        (["Cross-encoder", "Dense retrieval"], ["sentence"], True, False, []),
        (
            ["Hybrid retrieval", "Reranking", "Retrieval-augmented generation", "ColBERT"],
            ["bm25", "sentence"],
            True,
            True,
            ["ColBERT"],
        ),
        (
            ["Retrieval-augmented generation"],
            ["bm25"],
            False,
            True,
            [],
        ),  # retrieval needs a retriever
        (["RAG", "DPR"], ["dpr"], False, True, []),
        (["Retrieval-Augmented Generation (RAG)"], ["bm25"], False, True, []),
        (["Closed-book"], [], False, True, []),  # a model alone, nothing retrieved
        (["No retrieval"], [], False, True, []),
        (["Self-RAG", "FiD"], [], False, False, ["Self-RAG", "FiD"]),  # trained systems: not ours
        ([], [], False, False, []),
    ],
)
def test_names_from_a_plan_map_to_components(
    names: list[str], stages: list[str], rerank: bool, generate: bool, unmapped: list[str]
) -> None:
    plan = c.resolve(names)
    assert (plan.stages, plan.rerank, plan.generate, plan.unmapped) == (
        stages,
        rerank,
        generate,
        unmapped,
    )
    assert not plan.gate


@pytest.mark.parametrize(
    ("names", "stages"),
    [
        (["Adaptive retrieval"], ["bm25"]),  # a gate needs something to retrieve with
        (["Retrieve only when needed", "Contriever"], ["contriever"]),
        (["Selective retrieval", "Closed-book"], ["bm25"]),  # a gate chooses between the two
    ],
)
def test_gate_names_give_a_gated_generator(names: list[str], stages: list[str]) -> None:
    plan = c.resolve(names)
    assert plan.gate and plan.generate and plan.stages == stages and not plan.unmapped
    assert c.resolve(["Adaptive-RAG"]).unmapped == ["Adaptive-RAG"]  # a trained system: not ours


def test_a_description_says_what_the_pipeline_is() -> None:
    assert c.describe(["bm25"], False) == "BM25"
    text = c.describe(["bm25", "sentence"], True)
    assert (
        "BM25 + BGE-small" in text and "reciprocal rank fusion" in text and "cross-encoder" in text
    )
    assert (
        c.describe(["bm25"], False, True) == "BM25; a language model answers from the top passages"
    )
    assert "closed-book" in c.describe([], False, True)


# --- whole generated projects (offline: BM25 only) ----------------------------------------------


async def rows_of(project: Path) -> list[dict[str, str]]:
    return list(csv.DictReader((project / "results" / "results.csv").open(encoding="utf-8")))


async def test_an_approach_built_on_bm25_runs_now_and_says_it_is_a_starter(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(
        auth_client, ["toy"], baselines=("BM25", "ColBERT"), builds_on=("BM25",)
    )
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    result = run(tmp_path, "run_experiments.py", "--only", "main-1")
    assert result.returncode == 0, result.stderr
    rows = await rows_of(tmp_path)

    def recall1(system: str) -> float:
        return float(
            next(
                r["value"]
                for r in rows
                if r["system"] == system and r["metric"] == "recall@1" and r["seed"] == "0"
            )
        )

    approach = [r for r in rows if r["system"] == "Your approach" and r["status"] == "ok"]
    assert approach and all("starter pipeline: BM25" in r["note"] for r in approach)
    assert all("NOT implemented" not in r["note"] for r in approach)
    assert recall1("Your approach") == recall1("BM25") >= 0.75 > recall1("Random (sanity check)")
    assert all(r["status"] == "todo" for r in rows if r["system"] == "ColBERT")

    systems_py = (tmp_path / "systems.py").read_text(encoding="utf-8")
    assert "class YourApproach(PipelineSystem)" in systems_py
    assert "class Baseline_BM25(PipelineSystem)" in systems_py
    assert "class Baseline_ColBERT(System)" in systems_py
    assert "Your idea goes here" in systems_py
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "first runnable version" in readme and "**not your idea**" in readme
    assert "`BM25` (BM25): runs now" in readme and "(ColBERT): TODO stub" in readme


async def test_what_no_component_covers_is_named_not_hidden(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(
        auth_client,
        ["toy"],
        baselines=("ColBERT",),
        builds_on=("BM25", "Self-RAG"),
    )
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    assert run(tmp_path, "run_experiments.py", "--only", "main-1").returncode == 0
    approach = [
        r for r in await rows_of(tmp_path) if r["system"] == "Your approach" and r["status"] == "ok"
    ]
    assert approach and all(
        "NOT implemented (no component): Self-RAG" in r["note"] for r in approach
    )
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "No component implements: **Self-RAG**" in readme


async def test_with_nothing_to_assemble_the_approach_stays_a_todo(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(auth_client, ["toy"])  # builds on Self-RAG only: no component
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    assert run(tmp_path, "run_experiments.py", "--only", "main-1").returncode == 0
    mine = [r for r in await rows_of(tmp_path) if r["system"] == "Your approach"]
    assert mine and all(r["status"] == "todo" and r["value"] == "" for r in mine)
    assert "class YourApproach(System)" in (tmp_path / "systems.py").read_text(encoding="utf-8")
    assert "has a finished component, so there is no starter pipeline" in (
        tmp_path / "README.md"
    ).read_text(encoding="utf-8")


# --- real models (opt in) -----------------------------------------------------------------------


@MODEL_TESTS
def test_dense_and_reranker_components_rank_the_toy_questions() -> None:
    examples = data.load("toy")
    hybrid = c.build(["bm25", "sentence"], True)
    hybrid.prepare(examples)
    firsts = [hybrid.rank(ex)[0] for ex in examples]
    assert firsts == [ex["relevant"][0] for ex in examples]


@MODEL_TESTS
@pytest.mark.parametrize("stage", ["sentence", "contriever", "dpr"])
def test_each_dense_scorer_beats_chance_on_the_toy_questions(stage: str) -> None:
    examples = data.load("toy")
    pipeline = c.build([stage], False)
    pipeline.prepare(examples)
    top1 = sum(pipeline.rank(ex)[0] == ex["relevant"][0] for ex in examples)
    assert top1 >= 3, f"{stage} ranked the relevant passage first for only {top1} of 4 questions"


async def test_the_readme_warns_about_model_downloads_only_when_models_are_involved(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    light = await make_project(auth_client, ["toy"], baselines=("BM25",), builds_on=("BM25",))
    heavy = await make_project(
        auth_client, ["toy"], baselines=("DPR",), builds_on=("Hybrid retrieval", "Reranking")
    )
    texts = {}
    for name, pid in (("light", light), ("heavy", heavy)):
        files = (await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"]
        texts[name] = next(f["content"] for f in files if f["path"] == "README.md")
    assert "First run downloads models" not in texts["light"]
    note = texts["heavy"]
    assert "**First run downloads models**" in note
    assert "DPR (two encoders)" in note and "BGE-small" in note
    assert "the cross-encoder reranker" in note and "--limit 50" in note


async def test_overriding_rank_in_the_marked_place_changes_the_approach(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    """The README says the user's idea goes in YourApproach.rank; check that really works."""
    pid = await make_project(auth_client, ["toy"], baselines=("BM25",), builds_on=("BM25",))
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    systems_py = tmp_path / "systems.py"
    text = systems_py.read_text(encoding="utf-8")
    marker = "    # --- Your idea goes here"
    assert marker in text
    head, _, _ = text.partition(marker)
    override = (
        "    def rank(self, example: data.Example, seed: int) -> list[int]:\n"
        "        return list(reversed(super().rank(example, seed)))  # deliberately wrong\n"
    )
    # keep everything after YourApproach (the baselines and the registry); only its body changes
    after = text[text.index("\n\nclass Baseline_BM25") :]
    systems_py.write_text(head + override + after, encoding="utf-8")

    assert run(tmp_path, "run_experiments.py", "--only", "main-1").returncode == 0
    rows = await rows_of(tmp_path)
    recall = {
        r["system"]: float(r["value"])
        for r in rows
        if r["metric"] == "recall@1" and r["seed"] == "0" and r["status"] == "ok"
    }
    assert recall["BM25"] >= 0.75 and recall["Your approach"] == 0.0  # the override was used
