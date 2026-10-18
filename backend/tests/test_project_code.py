"""Step guides and the generated starter project — which is written to disk and actually run."""

from __future__ import annotations

import ast
import csv
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.projects import codegen
from app.services.projects.guide import GUIDES, STEP_ORDER
from app.services.projects.starter import metrics

API = "/api/v1"
HYPOTHESIS = "Approach X keeps accuracy within 2 points of DPR without labels."


async def make_project(
    client: AsyncClient,
    datasets: list[str],
    baselines: tuple[str, ...] = ("ColBERT", "Full fine-tuning"),
    builds_on: tuple[str, ...] = ("Self-RAG",),  # no component: the approach stays a stub
) -> str:
    created = await client.post(
        f"{API}/projects", json={"idea": "Retrieve only when needed without labels"}
    )
    pid = created.json()["id"]
    plan = {
        "datasets": datasets,
        "baselines": list(baselines),
        "methods": list(builds_on),
        "metrics": ["Accuracy", "Recall@k", "Perplexity"],
    }
    assert (
        await client.patch(
            f"{API}/projects/{pid}", json={"hypothesis": HYPOTHESIS, "methods": plan}
        )
    ).status_code == 200
    assert (await client.post(f"{API}/projects/{pid}/experiments", json={})).status_code == 200
    return str(pid)


def write_project(files: list[dict[str, str]], target: Path) -> None:
    for file in files:
        (target / file["path"]).write_text(file["content"], encoding="utf-8")


async def test_model_code_can_be_saved_in_the_project_workspace(auth_client: AsyncClient) -> None:
    pid = await make_project(auth_client, ["toy"])
    content = "class ResearchModel:\n    def forward(self, values):\n        return values\n"
    saved = await auth_client.put(
        f"{API}/projects/{pid}/code-file", json={"path": "model.py", "content": content}
    )
    assert saved.status_code == 200, saved.text
    files = (await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"]
    assert next(file["content"] for file in files if file["path"] == "model.py") == content

    unknown = await auth_client.put(
        f"{API}/projects/{pid}/code-file", json={"path": "../../server.py", "content": "bad"}
    )
    assert unknown.status_code == 422


async def test_python_syntax_check_reports_errors_without_executing_code(
    auth_client: AsyncClient,
) -> None:
    pid = await make_project(auth_client, ["toy"])
    valid = await auth_client.post(
        f"{API}/projects/{pid}/code-file/check",
        json={
            "path": "model.py",
            "content": "class ResearchModel:\n    def forward(self, values):\n        return values\n",
        },
    )
    assert valid.status_code == 200, valid.text
    assert valid.json() == {
        "valid": True,
        "message": "Valid Python syntax. The code was checked but not executed.",
        "line": None,
        "column": None,
    }

    invalid = await auth_client.post(
        f"{API}/projects/{pid}/code-file/check",
        json={"path": "model.py", "content": "class ResearchModel:\n    def forward(self):\n        return (\n"},
    )
    assert invalid.status_code == 200, invalid.text
    assert invalid.json()["valid"] is False
    assert invalid.json()["line"] == 3
    assert invalid.json()["message"]

    non_python = await auth_client.post(
        f"{API}/projects/{pid}/code-file/check",
        json={"path": "config.json", "content": "{}"},
    )
    assert non_python.status_code == 422


def run(cwd: Path, *args: str, env_path: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(env_path)} if env_path else None
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        env=env,
    )


async def test_the_generated_project_runs_and_never_invents_a_number(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(auth_client, ["toy"])
    body = (await auth_client.get(f"{API}/projects/{pid}/code")).json()
    files = body["files"]
    assert [f["path"] for f in files] == list(codegen.PURPOSE)
    assert all(f["purpose"] and f["content"].strip() for f in files)
    write_project(files, tmp_path)
    for file in files:
        if file["path"].endswith(".py"):
            ast.parse(file["content"])  # every generated Python file is valid

    config = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert config["hypothesis"] == HYPOTHESIS and config["datasets"] == ["toy"]
    assert [e["kind"] for e in config["experiments"]] == ["main", "ablation", "analysis"]
    assert config["experiments"][0]["systems"] == ["Your approach", "ColBERT", "Full fine-tuning"]

    # 1. The smoke test from the README works, and its own tests pass.
    smoke = run(tmp_path, "run_experiments.py", "--smoke")
    assert smoke.returncode == 0, smoke.stderr
    assert "Lexical overlap (sanity check)" in smoke.stdout and "recall@1" in smoke.stdout
    toy = run(tmp_path, "run_experiments.py", "--toy")
    assert toy.returncode == 0, toy.stderr
    toy_rows = list(
        csv.DictReader((tmp_path / "results" / "results.csv").open(encoding="utf-8"))
    )
    assert {row["dataset"] for row in toy_rows} == {"toy"}
    assert {row["seed"] for row in toy_rows if row["seed"] != "-"} == {"0"}
    assert {row["system"] for row in toy_rows} >= {
        "Your approach",
        "ColBERT",
        "Full fine-tuning",
        "Lexical overlap (sanity check)",
    }
    tests = run(tmp_path, "-m", "pytest", "-q", "-p", "no:cacheprovider")
    assert tests.returncode == 0, tests.stdout + tests.stderr

    # 2. A real run: finished systems get numbers, stubs get "todo" rows and nothing else.
    full = run(tmp_path, "run_experiments.py")
    assert full.returncode == 0, full.stderr
    rows = list(csv.DictReader((tmp_path / "results" / "results.csv").open(encoding="utf-8")))
    by_system: dict[str, set[str]] = {}
    for row in rows:
        by_system.setdefault(row["system"], set()).add(row["status"])
    assert by_system["Lexical overlap (sanity check)"] == {"ok"}
    for stub in ("Your approach", "ColBERT", "Full fine-tuning"):
        assert by_system[stub] == {"todo"}, stub
    assert all(r["value"] == "" for r in rows if r["status"] == "todo")
    notes = {r["note"] for r in rows if r["system"] == "ColBERT"}
    assert any("Baseline_ColBERT" in n for n in notes)
    assert any(r["metric"] == "Perplexity" and "metrics.py" in r["note"] for r in rows)
    assert "ablation" in full.stdout  # non-main experiments say what to do


async def test_a_dataset_without_a_loader_fails_loudly_with_a_pointer(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(auth_client, ["BEIR"])
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    result = run(tmp_path, "run_experiments.py", "--only", "main-1")
    assert result.returncode == 0, result.stderr
    assert "No loader for the dataset" in result.stdout
    assert "github.com/beir-cellar/beir" in result.stdout
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "load_beir" in readme and "not implemented" in readme  # Perplexity


async def test_the_readme_says_what_each_loader_gives(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    pid = await make_project(auth_client, ["MS MARCO", "Natural Questions", "toy"])
    write_project((await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"], tmp_path)
    readme = (tmp_path / "README.md").read_text(encoding="utf-8")
    assert "microsoft/ms_marco v2.1; re-ranking the 10 candidate passages" in readme
    assert "NQ-Open" in readme and "no passages" in readme
    assert "built in; four questions" in readme


async def test_the_code_downloads_as_a_zip(auth_client: AsyncClient) -> None:
    pid = await make_project(auth_client, ["squad"])
    response = await auth_client.get(f"{API}/projects/{pid}/export", params={"format": "code"})
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith('-starter-code.zip"')
    names = zipfile.ZipFile(io.BytesIO(response.content)).namelist()
    assert names == list(codegen.PURPOSE)


async def test_every_step_has_a_complete_guide_that_reflects_the_project(
    auth_client: AsyncClient,
) -> None:
    pid = await make_project(auth_client, ["toy", "squad"])
    assert set(GUIDES) == set(STEP_ORDER)
    seen: dict[str, Any] = {}
    for number, step in enumerate(STEP_ORDER, start=1):
        response = await auth_client.get(f"{API}/projects/{pid}/guide/{step}")
        assert response.status_code == 200, response.text
        guide = seen[step] = response.json()
        assert (guide["number"], guide["of"]) == (number, len(STEP_ORDER))
        assert guide["why"] and guide["expected"]
        assert len(guide["actions"]) >= 3 and all(
            a["title"] and a["detail"] for a in guide["actions"]
        )
        assert guide["checks"] and guide["pitfalls"] and guide["yours"]
        assert guide["previous"] == (STEP_ORDER[number - 2] if number > 1 else None)
        assert guide["next"] == (STEP_ORDER[number] if number < len(STEP_ORDER) else None)
    assert any("toy, squad" in line for line in seen["methods"]["yours"])
    assert any("ColBERT, Full fine-tuning" in line for line in seen["methods"]["yours"])
    assert any("4 experiments planned" in line for line in seen["experiments"]["yours"])
    assert any("Your hypothesis is written" in line for line in seen["gaps"]["yours"])
    assert (await auth_client.get(f"{API}/projects/{pid}/guide/nonsense")).status_code == 422


def test_metric_names_from_a_plan_become_real_metrics() -> None:
    assert [m.label for m in metrics.expand_metric("Recall@k")] == [
        "recall@1",
        "recall@5",
        "recall@10",
    ]
    with pytest.raises(metrics.UnknownMetric):
        metrics.expand_metric("BLEU-ish")


def test_an_experiment_uses_the_dataset_it_names() -> None:
    item = {"title": "Main comparison on TriviaQA", "setup": "x vs. y on TriviaQA"}
    assert codegen.dataset_for(item, ["Natural Questions", "TriviaQA"]) == "TriviaQA"
    assert codegen.dataset_for({"title": "Ablation", "setup": ""}, ["A", "B"]) == "A"
    assert codegen.dataset_for({"title": "Ablation", "setup": ""}, []) == "(choose a dataset)"


async def test_a_project_with_no_plan_still_gets_working_code(
    auth_client: AsyncClient, tmp_path: Path
) -> None:
    created = await auth_client.post(f"{API}/projects", json={"idea": "An idea with no plan yet"})
    pid = created.json()["id"]
    files = (await auth_client.get(f"{API}/projects/{pid}/code")).json()["files"]
    write_project(files, tmp_path)
    for file in files:
        if file["path"].endswith(".py"):
            ast.parse(file["content"])
    assert "You haven't chosen a dataset yet" in (tmp_path / "README.md").read_text(
        encoding="utf-8"
    )
    smoke = run(
        tmp_path, "run_experiments.py", "--smoke"
    )  # no experiments: nothing to run, no crash
    assert smoke.returncode == 0, smoke.stderr
    assert run(tmp_path, "-m", "pytest", "-q", "-p", "no:cacheprovider").returncode == 0
