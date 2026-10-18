"""Build a compact, per-example error analysis from the generated prediction JSONL."""

from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from typing import Any


MAX_CHARS = 10_000_000
MAX_RECORDS = 20_000
MAX_EXAMPLES = 10_000
MAX_SYSTEMS = 8
MAX_HARD_CASES = 20
MAX_SEEDS_PER_SYSTEM = 3


def _passage_snippets(value: Any, *, keep_relevance: bool = False) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    snippets = []
    for item in value[:2]:
        if isinstance(item, str):
            snippets.append({"index": len(snippets), "text": item[:400]})
        elif isinstance(item, dict) and isinstance(item.get("text"), str):
            index = item.get("index", len(snippets))
            if not isinstance(index, int):
                index = len(snippets)
            snippet = {"index": index, "text": item["text"][:400]}
            if keep_relevance:
                snippet["relevant"] = bool(item.get("relevant", False))
            snippets.append(snippet)
    return snippets


def _seed_order(run: dict[str, Any]) -> tuple[int, int | str]:
    try:
        return (0, int(run["seed"]))
    except ValueError:
        return (1, run["seed"])


def analyze_predictions_jsonl(
    jsonl_text: str,
    metric: str,
    *,
    higher_is_better: bool = True,
) -> dict[str, Any]:
    """Rank hard examples and compare per-system answers for one scored metric.

    The raw prediction file is not included in the return value. Only the 20 hardest
    examples, small evidence excerpts, and aggregate summaries are retained by the caller.
    """
    if len(jsonl_text) > MAX_CHARS:
        raise ValueError("The prediction file is larger than 10 MB. Export a smaller run.")
    if not metric.strip():
        raise ValueError("Choose a metric before analyzing predictions.")

    rows: list[dict[str, Any]] = []
    metrics: set[str] = set()
    for line_number, line in enumerate(jsonl_text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_number} is not valid JSON: {exc.msg}.") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Line {line_number} must contain a JSON object.")
        question = row.get("question")
        system = row.get("system")
        if not isinstance(question, str) or not question.strip() or not isinstance(system, str) or not system.strip():
            raise ValueError(f"Line {line_number} needs a non-empty question and system name.")
        scores = row.get("metric_scores", {})
        if scores is None:
            scores = {}
        if not isinstance(scores, dict):
            raise ValueError(f"Line {line_number} has an invalid metric_scores object.")
        for name, value in scores.items():
            try:
                score = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Line {line_number} has a non-numeric score for {name}.") from exc
            if not math.isfinite(score) or score < 0 or score > 1:
                raise ValueError(f"Line {line_number} has a score outside the expected 0–1 range for {name}.")
            metrics.add(str(name))
        rows.append(row)
        if len(rows) > MAX_RECORDS:
            raise ValueError(f"The file has more than {MAX_RECORDS:,} prediction rows. Export a smaller run.")

    if not rows:
        raise ValueError("The JSONL file contains no prediction rows.")
    if metric not in metrics:
        if not metrics:
            raise ValueError(
                "This prediction file has no per-example metric scores. Download the latest starter code and rerun the experiment."
            )
        raise ValueError(f"Metric {metric!r} is not present. Available metrics: {', '.join(sorted(metrics))}.")

    grouped: dict[tuple[str, str, str], dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    example_meta: dict[tuple[str, str, str], dict[str, Any]] = {}
    system_scores: dict[str, list[float]] = defaultdict(list)
    systems: set[str] = set()
    scored_rows = 0

    for row in rows:
        system = row["system"].strip()[:200]
        systems.add(system)
        if len(systems) > MAX_SYSTEMS:
            raise ValueError(f"The file has more than {MAX_SYSTEMS} systems. Export only the systems you want to compare.")
        experiment = str(row.get("experiment") or "experiment")[:200]
        dataset = str(row.get("dataset") or "dataset")[:200]
        question = row["question"].strip()
        example_id = str(row.get("example_id") or question)[:250]
        key = (experiment, dataset, example_id)
        if key not in example_meta:
            references = row.get("reference_answers", [])
            if not isinstance(references, list):
                references = []
            example_meta[key] = {
                "experiment": experiment,
                "dataset": dataset,
                "example_id": example_id,
                "question": question[:2_000],
                "reference_answers": [str(answer)[:500] for answer in references[:10]],
                "reference_passages": _passage_snippets(row.get("reference_passages")),
            }

        raw_score = (row.get("metric_scores") or {}).get(metric)
        score: float | None = float(raw_score) if raw_score is not None else None
        if score is not None:
            scored_rows += 1
            system_scores[system].append(score)
        grouped[key][system].append({
            "seed": str(row.get("seed", "-"))[:80],
            "score": round(score, 6) if score is not None else None,
            "answer": str(row.get("answer") or "")[:2_000],
            "used_passages": _passage_snippets(row.get("used_passages")),
            "retrieved_passages": _passage_snippets(row.get("retrieved_passages"), keep_relevance=True),
        })

    if len(grouped) > MAX_EXAMPLES:
        raise ValueError(f"The file contains more than {MAX_EXAMPLES:,} distinct questions. Export a smaller run.")

    summaries = [
        {
            "system": system,
            "scored_predictions": len(values),
            "mean_score": round(statistics.fmean(values), 6),
        }
        for system, values in sorted(system_scores.items())
    ]

    cases = []
    for key, per_system in grouped.items():
        system_results = []
        means = []
        for system, runs in sorted(per_system.items()):
            scored = [run["score"] for run in runs if run["score"] is not None]
            mean_score = statistics.fmean(scored) if scored else None
            if mean_score is not None:
                means.append(mean_score)
            ordered_runs = sorted(runs, key=_seed_order)
            scored_seed_count = len({run["seed"] for run in runs if run["score"] is not None})
            system_results.append({
                "system": system,
                "mean_score": round(mean_score, 6) if mean_score is not None else None,
                "scored_seeds": scored_seed_count,
                "run_count": len(runs),
                "runs": ordered_runs[:MAX_SEEDS_PER_SYSTEM],
            })
        case = {
            **example_meta[key],
            "systems": system_results,
            "best_system_score": round(max(means) if higher_is_better else min(means), 6) if means else None,
            "score_spread": round(max(means) - min(means), 6) if len(means) > 1 else None,
        }
        cases.append(case)

    cases.sort(
        key=lambda case: (
            case["best_system_score"] is None,
            (case["best_system_score"] or 0) if higher_is_better else -(case["best_system_score"] or 0),
            case["experiment"],
            case["example_id"],
        )
    )
    hard_cases = cases[:MAX_HARD_CASES]

    return {
        "metric": metric,
        "higher_is_better": higher_is_better,
        "records_seen": len(rows),
        "records_scored": scored_rows,
        "records_without_metric": len(rows) - scored_rows,
        "example_count": len(grouped),
        "systems": sorted(systems),
        "metrics": sorted(metrics),
        "summaries": summaries,
        "hard_case_count": min(len(cases), MAX_HARD_CASES),
        "cases": hard_cases,
        "notes": [
            "Hard cases are ranked by the strongest system's mean score for the selected metric.",
            "A system's displayed seed samples are limited to three; its mean uses every scored row in the file.",
            "Reference answers and passages are shown only when the prediction export contains them.",
            "Only this compact analysis is saved to the project; the uploaded JSONL is discarded.",
        ],
    }
