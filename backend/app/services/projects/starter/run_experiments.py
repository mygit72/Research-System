"""Runs the experiments listed in config.json and writes results/results.csv.

    python run_experiments.py --smoke     # toy data, sanity systems only: checks the pipeline
    python run_experiments.py             # your datasets and systems (after the TODOs are done)
    python run_experiments.py --only main-1 --limit 200
    python run_experiments.py --estimate  # model calls and prompt tokens a run needs; calls nothing

What it does, in order, for every experiment in config.json:
  1. loads the dataset (data.py);
  2. builds each system (systems.py) and runs it on every example, once per seed;
  3. computes every metric (metrics.py) per example and averages;
  4. appends one row per (experiment, system, seed, metric) to results/results.csv.
A system or metric that isn't implemented yet gets a row with status "todo" and the reason,
never a number; a language model that can't be reached gets a row with status "error" and the
fix (answers generated so far are cached: rerun to continue). Predictions — with the passages
each answer was made from — go to results/predictions_<experiment>.jsonl for error analysis.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path

import data
import generation
import metrics
import systems

ROOT = Path(__file__).parent
SANITY = ["Lexical overlap (sanity check)", "Random (sanity check)"]
FIELDS = ["experiment", "dataset", "system", "seed", "metric", "value", "status", "note"]


def evaluate(system: systems.System, examples: list[data.Example], metric_list: list, seed: int):
    """Per-metric mean over the examples, the per-example predictions, and why any metric got
    no score at all (it then becomes a "todo" row rather than a number)."""
    scores: dict[str, list[float]] = defaultdict(list)
    predictions = []
    families = {m.family for m in metric_list}
    missing: dict[str, str] = {}
    for ex in examples:
        record: dict = {"question": ex["question"]}
        ranking = answer = evidence = None
        if "retrieval" in families:
            ranking = system.rank(ex, seed)  # None: this system doesn't retrieve (closed-book)
            record["ranking"] = ranking
        if families & {"answer", "grounded"}:
            answer = system.answer(ex, seed)
            record["answer"] = answer
        if families & {"grounded", "evidence"}:
            evidence = system.evidence(ex, seed)  # None: the system doesn't say
            record["evidence"] = evidence
        for m in metric_list:
            if m.family == "retrieval":
                if ranking is None:
                    missing[m.label] = (
                        f"{system.label} doesn't retrieve, so {m.label} doesn't apply."
                    )
                else:
                    scores[m.label].append(m.compute(ranking, ex["relevant"]))
            elif m.family == "grounded":
                if evidence is None:
                    missing[m.label] = (
                        f"{system.label} doesn't say which passages its answer came from: give it "
                        "an evidence() method in systems.py."
                    )
                elif evidence:  # closed-book: nothing to be grounded in, not a 0
                    scores[m.label].append(m.compute(answer, [ex["passages"][i] for i in evidence]))
            elif m.family == "evidence":
                if evidence is None:
                    missing[m.label] = (
                        f"{system.label} doesn't say whether it used passages: give it an "
                        "evidence() method in systems.py."
                    )
                else:
                    scores[m.label].append(m.compute(evidence))
            elif ex["answers"]:  # no accepted answer: nothing to compare with, not a 0
                scores[m.label].append(m.compute(answer, ex["answers"]))
        predictions.append(record)
    for m in metric_list:
        if m.label not in scores:
            missing.setdefault(
                m.label,
                "No example could be scored: answer metrics need accepted answers, groundedness "
                "needs passages the answer was made from.",
            )
    result = {label: statistics.fmean(values) for label, values in scores.items()}
    return result, predictions, missing


def run(
    config: dict, smoke: bool, only: str | None, limit: int | None, estimate: bool = False
) -> list[dict]:
    rows: list[dict] = []
    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    seeds = config["seeds"]
    experiments = config["experiments"]
    if smoke:
        # The pipeline is the same for every experiment: run it once, on toy data, whatever
        # the plan says (even if it has no experiments yet), with retrieval metrics included
        # so the check is meaningful.
        main = next((e for e in experiments if e["kind"] == "main"), None)
        main = main or {"key": "smoke", "kind": "main", "title": "Smoke test", "how": ""}
        metric_names = list(dict.fromkeys([*config["metrics"], "Recall@k", "MRR"]))
        experiments = [{**main, "dataset": "toy", "systems": [], "metrics": metric_names}]
    for exp in experiments:
        if only and exp["key"] != only:
            continue
        if exp["kind"] != "main" and not smoke:
            print(f"[{exp['key']}] {exp['kind']}: {exp['title']} — {exp['how']}")
            continue
        dataset = exp["dataset"]
        names = SANITY if smoke else SANITY + exp["systems"]
        metric_list, todo_metrics = [], []
        for name in exp["metrics"]:
            try:
                metric_list += metrics.expand_metric(name, config["ks"])
            except metrics.UnknownMetric as exc:
                todo_metrics.append((name, str(exc)))
        base = {"experiment": exp["key"], "dataset": dataset}
        try:
            examples = data.load(dataset, config["split"], limit)
        except (NotImplementedError, ImportError, OSError) as exc:
            # no loader, `datasets` not installed, or no network for the download
            rows.append({**base, "system": "-", "seed": "-", "metric": "-", "value": "",
                         "status": "todo", "note": str(exc)})  # fmt: skip
            print(f"[{exp['key']}] {dataset}: TODO — {exc}")
            continue
        if any(m.family == "retrieval" for m in metric_list) and not all(
            ex["passages"] and ex["relevant"] for ex in examples
        ):
            # Scoring a ranking of nothing would report 0 and look like a result. Say why instead.
            note = (
                f"{dataset} has no candidate passages with relevance labels, so retrieval metrics "
                "can't be computed on it: they need a corpus and a retriever of your own."
            )
            for m in (m for m in metric_list if m.family == "retrieval"):
                todo_metrics.append((m.label, note))
            metric_list = [m for m in metric_list if m.family != "retrieval"]
        for name in names:
            for seed in seeds:
                try:
                    system = systems.build(name)
                    system.prepare(examples)
                    result, predictions, missing = evaluate(system, examples, metric_list, seed)
                except NotImplementedError as exc:
                    rows.append({**base, "system": name, "seed": seed, "metric": "-", "value": "",
                                 "status": "todo", "note": str(exc)})  # fmt: skip
                    print(f"[{exp['key']}] {name}: TODO — {exc}")
                    break
                except generation.GenerationError as exc:
                    note = f"{exc} (answers generated so far are cached: rerun to continue)"
                    rows.append({**base, "system": name, "seed": seed, "metric": "-", "value": "",
                                 "status": "error", "note": note})  # fmt: skip
                    print(f"[{exp['key']}] {name}: ERROR — {note}")
                    break
                for label, value in result.items():
                    rows.append({**base, "system": name, "seed": seed, "metric": label,
                                 "value": f"{value:.4f}", "status": "ok", "note": system.note})  # fmt: skip
                for label, why in missing.items():
                    rows.append({**base, "system": name, "seed": seed, "metric": label,
                                 "value": "", "status": "todo", "note": why})  # fmt: skip
                stats = getattr(system, "generation_stats", None)
                if stats is not None and (stats.generated or stats.cached or stats.estimated):
                    print(f"[{exp['key']}] {name}, seed {seed}: {stats.line()}")
                if estimate:
                    continue  # the answers are placeholders: nothing to keep
                path = out / f"predictions_{exp['key']}.jsonl"
                with path.open("a", encoding="utf-8") as handle:
                    for p in predictions:
                        handle.write(json.dumps({"system": name, "seed": seed, **p}) + "\n")
        for name, note in todo_metrics:
            rows.append({**base, "system": "-", "seed": "-", "metric": name, "value": "",
                         "status": "todo", "note": note})  # fmt: skip
    return rows


def summarize(rows: list[dict]) -> str:
    table: dict[tuple, list[float]] = defaultdict(list)
    for r in rows:
        if r["status"] == "ok":
            table[(r["experiment"], r["dataset"], r["system"], r["metric"])].append(
                float(r["value"])
            )
    lines = [
        "experiment | dataset | system | metric | mean ± std over seeds",
        "---|---|---|---|---",
    ]
    for (exp, ds, system, metric), values in sorted(table.items()):
        spread = statistics.pstdev(values) if len(values) > 1 else 0.0
        lines.append(
            f"{exp} | {ds} | {system} | {metric} | {statistics.fmean(values):.3f} ± {spread:.3f}"
        )
    todo = [r for r in rows if r["status"] == "todo"]
    if todo:
        lines += ["", f"{len(todo)} item(s) still TODO — see the note column of results.csv."]
    failed = [r for r in rows if r["status"] == "error"]
    if failed:
        lines += ["", f"{len(failed)} run(s) FAILED — see the note column of results.csv:"]
        lines += sorted({f"- {r['system']}: {r['note']}" for r in failed})
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--smoke", action="store_true", help="toy data and sanity systems only")
    parser.add_argument("--only", help="run one experiment key, e.g. main-1")
    parser.add_argument("--limit", type=int, help="use at most this many examples")
    parser.add_argument(
        "--estimate",
        action="store_true",
        help="count the model calls and prompt tokens a run needs, without calling the model",
    )
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    if args.estimate:
        generation.Generator.estimate_only = True
        run(config, args.smoke, args.only, args.limit, estimate=True)
        calls, tokens = generation.estimate_totals()
        print(
            f"\nEstimate: {calls} model call(s) not in the cache, ~{tokens} prompt tokens (about "
            f"{generation.CHARS_PER_TOKEN} characters per token), plus up to max_tokens per answer."
            "\nFor a gated system this is an upper bound: it counts a second call for every "
            "question, as if the model always declined first.\nNothing was called or written."
        )
        return
    for stale in (ROOT / "results").glob("predictions_*.jsonl"):
        stale.unlink()
    rows = run(config, args.smoke, args.only, args.limit)
    (ROOT / "results").mkdir(exist_ok=True)
    with (ROOT / "results" / "results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = summarize(rows)
    (ROOT / "results" / "summary.md").write_text(summary + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
