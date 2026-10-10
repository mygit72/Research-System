"""A starter code project generated from the user's plan.

Nothing here is written by a language model. The files that don't depend on the plan
(`metrics.py`, `data.py`, `run_experiments.py`) are real, tested modules in `starter/`; the
plan-specific ones (`config.json`, `systems.py`, `README.md`) are filled in from what the user
chose: datasets, baselines, methods, metrics, the experiments and the hypothesis.

What is *not* known stays a visible TODO: the user's own approach and the baselines are stubs
that raise `NotImplementedError` with instructions, so a run can never report a number for a
system nobody implemented.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.models.project import ResearchProject
from app.services.llm.user_models import active_model
from app.services.projects import systems_template as tpl
from app.services.projects.service import _steps
from app.services.projects.starter import components as starter_components
from app.services.projects.starter import data as starter_data
from app.services.projects.starter import generation as starter_generation
from app.services.projects.starter import metrics as starter_metrics

# The environment variable the downloaded project reads the user's key from, per provider.
KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "custom": "OPENAI_API_KEY",
}

STARTER = Path(__file__).parent / "starter"
STATIC = ("metrics.py", "data.py", "components.py", "generation.py", "run_experiments.py")
APPROACH = "Your approach"
SEEDS = [0, 1, 2]

PURPOSE = {
    "README.md": "The walkthrough: what to run, in which order, what you should see, and how to judge it.",
    "config.json": "Your plan as data: datasets, systems, metrics and the experiments to run.",
    "systems.py": "The systems being compared. Your approach and the baselines are TODO stubs for you to implement.",
    "components.py": "Finished building blocks: BM25, DPR, Contriever, a sentence-transformer, RRF fusion, a cross-encoder reranker.",
    "generation.py": "Answers written by a language model (Ollama or an OpenAI-compatible API) from the retrieved passages; cached and logged.",
    "metrics.py": "Metrics (accuracy, exact match, F1, contains, groundedness, recall@k, precision@k, MRR, nDCG), implemented and tested.",
    "data.py": "Dataset loading: a built-in toy set for the smoke test, SQuAD, and pointers for the rest.",
    "run_experiments.py": "Runs every planned experiment and writes results/results.csv and summary.md.",
    "test_pipeline.py": "Tests that the metrics are right and the smoke run works. Run: python -m pytest",
    "requirements.txt": "Python packages (only needed for real datasets and your own systems).",
}


def _slug(name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z]+", "_", name).strip("_") or "system"


def dataset_for(item: dict[str, Any], datasets: list[str]) -> str:
    """The chosen dataset an experiment mentions, else the first chosen one."""
    text = f"{item.get('title', '')} {item.get('setup', '')}".lower()
    for dataset in sorted(datasets, key=len, reverse=True):
        if dataset.lower() in text:
            return dataset
    return datasets[0] if datasets else "(choose a dataset)"


def _used_by(project: ResearchProject, name: str) -> list[str]:
    suggestions = _steps(project)["methods"].get("suggestions") or {}
    titles: list[str] = []
    for entries in suggestions.values():
        for entry in entries:
            if entry["name"].lower() == name.lower():
                titles += [p["title"] for p in entry.get("papers", [])]
    return list(dict.fromkeys(titles))


def generator_config(settings: Settings | None) -> dict[str, Any]:
    """The language model the user works with here (their choice in Settings → AI, else the
    server's), for the starter's generator. Never the API key: the starter reads it from an
    environment variable on the user's machine (`api_key_env`), so config.json can be shared."""
    user = active_model()
    if user is not None and not user.free:  # the free shared model is the server's: below
        provider, base_url = user.provider, user.base_url
        model, key_env = user.model, KEY_ENV.get(user.preset, "OPENAI_API_KEY")
    else:
        provider = settings.llm_provider if settings else "ollama"
        if provider not in starter_generation.DEFAULTS:  # "fake" (tests, demo): a local model
            provider = "ollama"
        model = (settings.llm_model if settings and provider == settings.llm_provider else "") or ""
        base_url = starter_generation.DEFAULTS[provider]["base_url"]
        if settings and provider == "ollama":
            base_url = settings.ollama_base_url
        elif settings and provider == "openai":
            base_url = settings.llm_api_base
        key_env = "OPENAI_API_KEY"
    config: dict[str, Any] = {
        "provider": provider,
        "model": model or starter_generation.DEFAULTS[provider]["model"],
        "base_url": base_url,
        "top_k": 3,
        "max_tokens": 64,
    }
    if provider != "ollama":
        config["api_key_env"] = key_env
    config["timeout"] = settings.llm_timeout if settings else 300.0
    return config


def _plans(config: dict[str, Any]) -> list[starter_components.Plan]:
    """Your approach's plan, then one per baseline."""
    resolve = starter_components.resolve
    return [resolve(config["builds_on"]), *(resolve([b]) for b in config["baselines"])]


def _runs(plan: starter_components.Plan) -> bool:
    return bool(plan.stages or plan.generate)


def _describe(plan: starter_components.Plan) -> str:
    return starter_components.describe(plan.stages, plan.rerank, plan.generate, plan.gate)


def _generates(config: dict[str, Any]) -> bool:
    return any(plan.generate for plan in _plans(config))


def _gates(config: dict[str, Any]) -> bool:
    return any(plan.gate for plan in _plans(config))


def build_config(project: ResearchProject, settings: Settings | None = None) -> dict[str, Any]:
    steps = _steps(project)
    chosen = steps["methods"]["chosen"]
    datasets = chosen.get("datasets") or []
    baselines = chosen.get("baselines") or []
    metrics = chosen.get("metrics") or ["Accuracy"]
    experiments = []
    for item in steps["experiments"]["items"]:
        experiments.append(
            {
                "key": item["key"],
                "kind": item["kind"],
                "title": item["title"],
                "dataset": dataset_for(item, datasets),
                "systems": [APPROACH, *baselines],
                "metrics": item.get("metrics") or metrics,
                "how": item.get("setup", ""),
            }
        )
    config = {
        "project": project.title,
        "hypothesis": project.hypothesis,
        "split": "validation",
        "seeds": SEEDS,
        "ks": list(starter_metrics.DEFAULT_KS),
        "datasets": datasets,
        "baselines": baselines,
        "builds_on": chosen.get("methods") or [],
        "metrics": metrics,
        "experiments": experiments,
        "generator": generator_config(settings),
    }
    if _gates(config):
        config["gate"] = {"policy": "abstain", "threshold": starter_generation.GATE_THRESHOLD}
    return config


def build_systems(project: ResearchProject) -> str:
    chosen = _steps(project)["methods"]["chosen"]
    builds_on = chosen.get("methods") or []
    hypothesis = _one_line(project.hypothesis.strip() or "(write your hypothesis in the project)")
    plan = starter_components.resolve(builds_on)
    registry = [f"    {APPROACH!r}: YourApproach,"]
    parts = [tpl.SYSTEMS_HEAD]
    if _runs(plan):
        parts.append(
            tpl.APPROACH_RUNNABLE.format(
                hypothesis=hypothesis,
                builds_on=_one_line(", ".join(builds_on)),
                described=_describe(plan),
                unmapped_line=(
                    "Not implemented (no component covers it): "
                    f"{_one_line(', '.join(plan.unmapped))}."
                    if plan.unmapped
                    else "Every item you chose to build on is covered by a component."
                ),
                label=APPROACH,
                stages=plan.stages,
                rerank=plan.rerank,
                generate=plan.generate,
                gate=plan.gate,
                unmapped=plan.unmapped,
            )
        )
    else:
        parts.append(
            tpl.APPROACH_STUB.format(
                hypothesis=hypothesis,
                builds_on_line=(
                    f"Builds on: {_one_line(', '.join(builds_on))}."
                    if builds_on
                    else "You haven't chosen what it builds on."
                ),
                unmapped_line=(
                    "None of these has a finished component, so there is no starter pipeline."
                    if builds_on
                    else ""
                ),
                label=APPROACH,
            )
        )
    for name in chosen.get("baselines") or []:
        cls = f"Baseline_{_slug(name)}"
        used = _used_by(project, name)
        where = (
            f"Used by: {'; '.join(used)}."
            if used
            else "None of your papers is recorded as using it."
        )
        base = starter_components.resolve([name])
        if _runs(base):
            parts.append(
                tpl.BASELINE_RUNNABLE.format(
                    cls=cls,
                    name=_one_line(name),
                    where=_one_line(where),
                    described=_describe(base),
                    stages=base.stages,
                    rerank=base.rerank,
                    generate=base.generate,
                    gate=base.gate,
                )
            )
        else:
            parts.append(
                tpl.BASELINE_STUB.format(cls=cls, name=_one_line(name), where=_one_line(where))
            )
        registry.append(f"    {name!r}: {cls},")
    parts.append(
        "\n\nREGISTRY: dict[str, type[System]] = {\n"
        "    LexicalOverlap.label: LexicalOverlap,\n"
        "    Random.label: Random,\n" + "\n".join(registry) + "\n}\n"
    )
    parts.append(tpl.SYSTEMS_TAIL)
    return "".join(parts)


def _one_line(text: str) -> str:
    return " ".join(text.replace('"""', "'''").replace("\\", "/").split())


def _metric_status(names: list[str]) -> list[str]:
    lines = []
    for name in names:
        try:
            labels = ", ".join(m.label for m in starter_metrics.expand_metric(name))
            lines.append(f"- **{name}** → `{labels}` (implemented)")
        except starter_metrics.UnknownMetric:
            lines.append(f"- **{name}** → not implemented: add it to `metrics.py` before using it")
    return lines


def _dataset_status(names: list[str]) -> list[str]:
    lines = []
    for name in names:
        loader = starter_data.find_loader(name)
        if loader is not None:
            lines.append(
                f"- **{name}** → loader included in `data.py`: {loader.note}. Needs `pip install datasets` "
                "(except the built-in toy set)."
            )
        else:
            pointer = starter_data.POINTERS.get(starter_data.compact(name))
            where = f" Where to look: {pointer}." if pointer else ""
            lines.append(
                f"- **{name}** → no loader yet: write `load_{starter_data.compact(name)}` in `data.py`.{where}"
            )
    return lines


def _systems_section(config: dict[str, Any]) -> list[str]:
    plan = starter_components.resolve(config["builds_on"])
    lines = [
        "Open `systems.py`. Three kinds of system are in it:",
        "",
        "- **sanity systems** (finished) — a floor; a real system that doesn't beat *Random* has a bug;",
        "- **systems assembled from the finished components** in `components.py`: they run as they are and",
        "  say so in `results.csv` (`starter pipeline: …`). They use *public pretrained checkpoints* —",
        "  nothing is trained — so a score is comparable to a paper's only if you use the paper's data",
        "  and settings;",
        "- **TODO stubs** for everything no component covers: they produce `todo` rows, never numbers.",
        "",
        "**Baselines.** Do these first: a baseline you reproduce lets you check your setup against the",
        "number its paper reports.",
        "",
    ]
    for baseline in config["baselines"]:
        base = starter_components.resolve([baseline])
        status = (
            f"runs now — {_describe(base)}"
            if _runs(base)
            else "TODO stub — no component implements it; implement it as its paper describes, or use its released code"
        )
        lines.append(f"- `{_slug(baseline)}` ({baseline}): {status}")
    if not config["baselines"]:
        lines.append("- You haven't chosen a baseline yet (step *Methods*).")
    lines += ["", "**Your approach.**", ""]
    if _runs(plan):
        lines += [
            f"`YourApproach` is a *first runnable version*: {_describe(plan)}.",
            "That is assembled from what you chose to build on — it is **not your idea**. It is there so",
            "your experiments run end to end today and you have a working system to change. What makes your",
            "approach new is whatever you do *differently* from these parts; that goes in `rank()` in the",
            "marked place. Ways to start (edits to `YourApproach.rank`, or `answer` for generation):",
            "",
            "- change the scores: call a scorer yourself and combine, e.g.",
            "  `scores = components.BM25Scorer().score(example)` mixed with your own signal;",
            "- change the fusion: weights instead of `components.rrf`, or a different rank constant;",
            "- add a stage: filter, expand the question, or gate (skip retrieval when the first-stage",
            "  scores are flat) before returning the order;",
            "- replace a scorer with a model you trained: give it `score(example) -> list[float]`;",
            "- change the generation: what passages the model sees (`evidence`), its instruction",
            "  (`generation.SYSTEM_RAG`), or answer closed-book when retrieval looks useless — call",
            "  `self._generator.answer(question, [])`.",
            "",
            "Run it unchanged first and keep that result: your idea has to beat *it*, not just *Random*.",
        ]
        if plan.unmapped:
            lines += [
                "",
                "No component implements: "
                + ", ".join(f"**{u}**" for u in plan.unmapped)
                + ". They are not",
                "in the starter pipeline — they are part of what you still have to build.",
            ]
    else:
        lines += [
            "`YourApproach` is a TODO stub: none of what you chose to build on ("
            + (", ".join(config["builds_on"]) or "nothing chosen")
            + ") has a finished component, so there is no starter pipeline. Implement `rank()` and/or",
            "`answer()`; `components.py` has a BM25 scorer, fusion and a reranker you can call from it.",
        ]
    lines += [""]
    if _generates(config):
        lines += _generation_section(config)
    if _gates(config):
        lines += _gate_section(config)
    return lines


def _gate_section(config: dict[str, Any]) -> list[str]:
    plans = _plans(config)
    names = [APPROACH, *config["baselines"]]
    gated = [name for name, plan in zip(names, plans, strict=True) if plan.gate]
    always = any(p.generate and p.stages and not p.gate for p in plans[1:])
    never = any(p.generate and not p.stages for p in plans[1:])
    missing = [
        label
        for label, present in (
            ("`RAG` (always retrieve)", always),
            ("`Closed-book` (never)", never),
        )
        if not present
    ]
    gate = config["gate"]
    return [
        "**The retrieval gate.** "
        + ", ".join(f"*{n}*" for n in gated)
        + (" decides" if len(gated) == 1 else " decide")
        + " per question whether to retrieve (the `gate` block of",
        f'`config.json`, now `"policy": "{gate["policy"]}"`):',
        "",
        '- `"abstain"` (no tuning): the model answers closed-book first; only if it says `unanswerable`',
        "  are the top passages retrieved and the question asked again with them. A question answered",
        "  closed-book costs one model call, a retrieved one two. It trusts the model to know what it",
        "  doesn't know — a small model that guesses instead never retrieves: watch the retrieval rate.",
        '- `"retriever"`: retrieve only when the top first-stage score is at least `threshold`',
        "  standard deviations above the mean of the candidates (`components.Pipeline.confidence`),",
        f"  else answer closed-book. {gate['threshold']} is only a starting point: choose the threshold on a",
        "  validation split, never on the test set. With a single candidate per question (SQuAD) there",
        "  is nothing to compare, so it always retrieves.",
        "- Add `Retrieval rate` to `metrics` in `config.json`: the share of questions answered from",
        "  passages. A gate is worth it when it keeps accuracy close to always retrieving while",
        "  retrieving less, so compare it with *always* and *never* retrieving"
        + (
            ": add " + " and ".join(missing) + " as baselines in *Methods*."
            if missing
            else " (both are in your baselines)."
        ),
        "- Retrieval metrics (recall@k, …) still rank every question: they describe the retriever, not",
        "  the gate.",
        "",
    ]


def _generation_section(config: dict[str, Any]) -> list[str]:
    g = config["generator"]
    where = {
        "ollama": [
            f"a local model through Ollama at {g['base_url']}: nothing leaves your machine. Install",
            f"Ollama (https://ollama.com), start it, and run `ollama pull {g['model']}` first.",
        ],
        "openai": [
            f"an OpenAI-compatible API at {g['base_url']}. Your key is read from the environment",
            f"variable `{g.get('api_key_env', 'OPENAI_API_KEY')}` on your computer (a local server",
            "may need none) — it is never written into these files. Windows:",
            f'`setx {g.get("api_key_env", "OPENAI_API_KEY")} "<your key>"` (open a new terminal',
            f"after); macOS / Linux: `export {g.get('api_key_env', 'OPENAI_API_KEY')}=<your key>`.",
        ],
    }[g["provider"]]
    return [
        "**Generation.** Systems marked *a language model answers from the top passages* send the",
        f"top {g['top_k']} passages and the question to `{g['provider']}:{g['model']}` (the `generator` block",
        "of `config.json`: the model you use in this app, from Settings → AI — change it freely).",
        "That is",
        *where,
        "",
        "- The model is told to answer in a few words, or exactly `unanswerable`. Decoding is greedy",
        "  where the API allows it, and every answer is cached in `cache/generations.jsonl` with its",
        "  prompt, tokens and time: reruns and extra seeds cost nothing, and an interrupted run resumes.",
        "  Open that file to see exactly what the model was asked.",
        "- One example is one model call. On a CPU a 3B model takes ~5–30 s per answer; a paid API",
        "  costs money per call. Start with `--limit 50`, and run `python run_experiments.py",
        "  --estimate` first: it counts the calls and prompt tokens a run needs without calling the model.",
        "- MS MARCO's accepted answers are sentences, so its loader asks for a one-sentence answer",
        "  (`answer_style`); every other dataset gets the few-words instruction.",
        '- Language models write "It was the Denver Broncos", which exact match scores as wrong. Add',
        "  `Contains` (an accepted answer appears in the reply) and `Groundedness` (a lexical check",
        "  that the answer's words come from the passages it was given — *not* a faithfulness score)",
        "  to `metrics` in `config.json`, next to exact match. `Abstention rate` shows how often the",
        "  model said `unanswerable`.",
        "- A high abstention rate often means the answer wasn't in the top passages, not that the",
        "  model failed: multi-hop questions (HotpotQA) need *every* supporting paragraph. Check",
        "  recall at `top_k` and raise `top_k` before blaming the model.",
        "- If the model can't be reached the run records an `error` row with the fix, never a number.",
        "",
    ]


def _download_note(config: dict[str, Any]) -> list[str]:
    """Dense scorers and the reranker download a model on first use: say so before it happens."""
    plans = _plans(config)
    stages = [s for plan in plans for s in plan.stages]
    rerank = any(plan.rerank for plan in plans)
    heavy = sorted({s for s in stages if s != "bm25"})
    if not heavy and not rerank:
        return []
    names = {"dpr": "DPR (two encoders)", "contriever": "Contriever", "sentence": "BGE-small"}
    models = [names[s] for s in heavy] + (["the cross-encoder reranker"] if rerank else [])
    return [
        "**First run downloads models** ("
        + ", ".join(models)
        + "; each is tens to a few hundred MB,",
        "needs `pip install sentence-transformers`). They run on a CPU, slowly: start with `--limit 50`.",
        "BM25 and the sanity systems need nothing.",
        "",
    ]


def build_readme(project: ResearchProject, config: dict[str, Any]) -> str:
    papers = {t for n in config["baselines"] + config["builds_on"] for t in _used_by(project, n)}
    experiments = [e for e in config["experiments"] if e["kind"] == "main"]
    lines = [
        f"# {config['project']} — starter code",
        "",
        "Generated from your project plan. It is a *scaffold*: the evaluation machinery is finished and",
        "tested; your approach and the baselines are for you to implement. It never reports a number",
        "for something that isn't implemented.",
        "",
        f"**Hypothesis:** {config['hypothesis'] or '_not written yet_'}",
        "",
        "## The files",
        "",
        *[f"- `{name}` — {PURPOSE[name]}" for name in PURPOSE],
        "",
        "## Step by step",
        "",
        "### 1. Set up",
        "",
        "```bash",
        "python -m venv .venv",
        ".venv/Scripts/activate        # Windows;  source .venv/bin/activate on Linux / macOS",
        "pip install -r requirements.txt",
        "```",
        "",
        "Why: the smoke test below needs nothing but Python, but loading real datasets and your own",
        "models needs these packages. Do it now so the first failure isn't a missing import.",
        "",
        "### 2. Check the pipeline (smoke test)",
        "",
        "```bash",
        "python run_experiments.py --smoke",
        "python -m pytest",
        "```",
        "",
        "What it does: runs the two finished sanity systems on a 4-question toy dataset and prints a",
        "table. **What you should see:** both systems with a row per metric, `Lexical overlap` clearly",
        "above `Random` on retrieval metrics (e.g. recall@1), no traceback, and the tests passing.",
        "If not, stop and fix that first — every later number depends on this machinery.",
        "",
        "### 3. Read `config.json`",
        "",
        "It is your plan as data: the datasets, baselines and metrics you chose, three seeds, the cut-offs",
        "for @k metrics (`ks`), and one entry per planned experiment (`main` comparisons run now;",
        "`ablation` and `analysis` print what to do). Change it freely — the runner reads it each time.",
        "",
        "### 4. Get your datasets",
        "",
        *(
            _dataset_status(config["datasets"])
            or ["- You haven't chosen a dataset yet (step *Methods*)."]
        ),
        "",
        "Every example has the same four keys (`question`, `passages`, `relevant`, `answers`; see",
        "`data.py`). Fix the split once and don't tune on the test set. Check each dataset's license.",
        "",
        "### 5. Your systems: what already runs, and what is yours to write",
        "",
        *_systems_section(config),
        *(
            ["Papers in your project that use these: " + "; ".join(sorted(papers)) + ".", ""]
            if papers
            else []
        ),
        "### 6. Metrics",
        "",
        *(_metric_status(config["metrics"])),
        "",
        "Retrieval metrics read `rank()`, answer metrics read `answer()`, groundedness reads `answer()`",
        "and `evidence()` — a system needs the ones its metrics use.",
        "",
        "### 7. Run the main experiments",
        "",
        *_download_note(config),
        *(
            [
                f"**Generation needs its model running** (`{config['generator']['provider']}:"
                f"{config['generator']['model']}`, see step 5) before the systems that generate can answer.",
                "",
            ]
            if _generates(config)
            else []
        ),
        "```bash",
        *[f"python run_experiments.py --only {e['key']}   # {e['title']}" for e in experiments[:3]],
        "python run_experiments.py                      # all of them",
        "```",
        "",
        "Start with `--limit 50` to catch bugs cheaply. Results go to `results/results.csv` (one row per",
        "experiment, system, seed, metric) and `results/summary.md` (mean ± spread over seeds).",
        "**What you should see:** every system you finished has numbers; unfinished ones show `todo`",
        "with the reason. Your approach should beat `Random` by a wide margin; your reproduced baselines",
        "should land near the numbers in their papers — if one is far off, suspect your setup, not the paper.",
        "",
        "### 8. Judge the result against your hypothesis",
        "",
        f"> {config['hypothesis'] or 'Write a hypothesis with a number in it, e.g. “within 2 points of X”.'}",
        "",
        "Compare the means *and* the spread over seeds. A difference smaller than the spread is not a",
        "result. Use more seeds or examples before claiming anything.",
        "",
        "### 9. Ablation and error analysis",
        "",
        *[f"- **{e['title']}** — {e['how']}" for e in config["experiments"] if e["kind"] != "main"],
        "",
        "Ablation: switch off one component of your approach at a time (add a variant class per",
        "component) and rerun the main comparison. Error analysis: `results/predictions_*.jsonl` has",
        "every prediction — open the examples your approach gets wrong and group them.",
        "",
        "### 10. Bring it back into the paper",
        "",
        "Put the final numbers into the *Experiments* section of your outline, say how many seeds and",
        "which split, and report where your approach does **not** help. Keep `config.json` and",
        "`results.csv` with the paper so anyone can rerun it.",
        "",
        "## Checklist for results you can trust",
        "",
        "- [ ] Same split, preprocessing and evaluation script for every system",
        "- [ ] Baselines reproduced against their papers' reported numbers",
        "- [ ] Nothing tuned on the test set",
        "- [ ] At least three seeds, spread reported",
        "- [ ] Dataset licenses checked, versions recorded",
        "",
    ]
    return "\n".join(lines)


def _requirements() -> str:
    return "datasets>=2.18\nsentence-transformers>=3\npytest>=8\n"


def starter_files(
    project: ResearchProject, settings: Settings | None = None
) -> list[dict[str, str]]:
    """Every file with its purpose, in reading order."""
    config = build_config(project, settings)
    content = {
        "README.md": build_readme(project, config),
        "config.json": json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        "systems.py": build_systems(project),
        "requirements.txt": _requirements(),
    }
    for name in (*STATIC, "test_pipeline.py"):
        content[name] = (STARTER / name).read_text(encoding="utf-8")
    return [{"path": name, "purpose": PURPOSE[name], "content": content[name]} for name in PURPOSE]


def starter_zip(project: ResearchProject, settings: Settings | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in starter_files(project, settings):
            archive.writestr(file["path"], file["content"])
    return buffer.getvalue()
