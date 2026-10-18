"""Compare one imported run summary with a cited result reported in a paper."""

from __future__ import annotations

import math
import re
from typing import Any


def _label(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def assess_paper_run_match(
    *,
    paper_dataset: str,
    paper_system: str,
    paper_metric: str,
    paper_split: str,
    run_dataset: str,
    run_system: str,
    run_metric: str,
    run_split: str,
    reported_mean: float,
    reproduced_mean: float,
    tolerance: float,
    map_labels: bool = False,
    mapping_note: str | None = None,
) -> dict[str, Any]:
    """Only compare the values when the evaluation protocol is aligned.

    The run CSV does not carry its split, so the supplied run split is retained as a
    user-confirmed protocol detail. Dataset/metric/system aliases need an explicit note.
    """
    label_pairs = {
        "dataset": (paper_dataset, run_dataset),
        "system": (paper_system, run_system),
        "metric": (paper_metric, run_metric),
    }
    label_mismatches = [
        {"field": field, "paper": paper_value, "run": run_value}
        for field, (paper_value, run_value) in label_pairs.items()
        if _label(paper_value) != _label(run_value)
    ]
    split_matches = _label(paper_split) == _label(run_split)
    mapping_confirmed = bool(map_labels and mapping_note and len(mapping_note.strip()) >= 8)

    if not split_matches or (label_mismatches and not mapping_confirmed):
        status = "not_comparable"
        alignment = "not_comparable"
    else:
        alignment = "user_mapped" if label_mismatches else "exact"
        status = "within_tolerance" if abs(reproduced_mean - reported_mean) <= tolerance else "diverged"

    difference = reproduced_mean - reported_mean
    relative_difference = (
        abs(difference) / abs(reported_mean) * 100 if reported_mean != 0 else None
    )
    if not math.isfinite(difference) or (relative_difference is not None and not math.isfinite(relative_difference)):
        raise ValueError("The reported and reproduced values are outside the supported numeric range.")

    return {
        "status": status,
        "alignment": alignment,
        "label_mismatches": label_mismatches,
        "split_matches": split_matches,
        "mapping_note": mapping_note.strip() if mapping_confirmed and mapping_note else None,
        "reported_mean": round(reported_mean, 6),
        "reproduced_mean": round(reproduced_mean, 6),
        "difference": round(difference, 6),
        "absolute_difference": round(abs(difference), 6),
        "relative_difference_percent": round(relative_difference, 3) if relative_difference is not None else None,
        "tolerance": round(tolerance, 6),
    }
