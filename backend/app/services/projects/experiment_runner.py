"""A deterministic, safe reference run for teaching scaled dot-product attention.

This module deliberately runs a fixed calculation. It never imports or executes project
code, reads user files, starts subprocesses, or calls a network service.
"""

from __future__ import annotations

import math
import random
from typing import Any


TOKENS = ["The", "model", "learns", "context"]
QUERY = [
    [0.2, 0.8],
    [0.9, 0.7],
    [0.7, 0.6],
    [0.2, 0.9],
]
KEY = [
    [0.2, 0.3],
    [0.8, 0.7],
    [0.6, 0.5],
    [0.1, 0.9],
]
VALUE = [
    [0.9, 0.1],
    [0.6, 0.9],
    [0.2, 0.8],
    [0.1, 0.6],
]


def _rounded(matrix: list[list[float]]) -> list[list[float]]:
    return [[round(value, 5) for value in row] for row in matrix]


def _mean_entropy(weights: list[list[float]]) -> float:
    entropy = [-sum(p * math.log(p) for p in row if p > 0) for row in weights]
    return round(sum(entropy) / len(entropy), 5)


def _variant(scale: float, *, name: str, label: str, formula: str) -> dict[str, Any]:
    scores = [
        [sum(q * k for q, k in zip(query, key, strict=True)) / scale for key in KEY]
        for query in QUERY
    ]
    weights = []
    for row in scores:
        maximum = max(row)
        exponentials = [math.exp(value - maximum) for value in row]
        total = sum(exponentials)
        weights.append([value / total for value in exponentials])
    output = [
        [
            sum(weight * VALUE[index][dimension] for index, weight in enumerate(row))
            for dimension in range(len(VALUE[0]))
        ]
        for row in weights
    ]
    return {
        "key": name,
        "label": label,
        "formula": formula,
        "score_matrix": _rounded(scores),
        "attention_weights": _rounded(weights),
        "output": _rounded(output),
        "mean_entropy_nats": _mean_entropy(weights),
    }


def run_reference_attention(score_divisor: float = 1.0) -> dict[str, Any]:
    """Compare paper scaling with a user-selected divisor on fixed vectors."""
    scaled = _variant(
        math.sqrt(len(QUERY[0])),
        name="paper_scaled",
        label="Paper: scaled dot-product",
        formula="softmax(QKᵀ / √dₖ) V",
    )
    if abs(score_divisor - 1.0) < 0.00001:
        variant_label = "Ablation: no scaling"
    else:
        variant_label = f"Your setting: divisor {score_divisor:g}"
    user_variant = _variant(
        score_divisor,
        name="user_setting",
        label=variant_label,
        formula=f"softmax(QKᵀ / {score_divisor:g}) V",
    )
    difference = scaled["mean_entropy_nats"] - user_variant["mean_entropy_nats"]
    if abs(difference) < 0.00001:
        interpretation = "The two variants have nearly the same mean attention entropy on these inputs."
    elif difference > 0:
        interpretation = (
            "The scaled variant spreads attention more evenly on these inputs, as shown by its "
            "higher mean entropy."
        )
    else:
        interpretation = (
            "The scaled variant concentrates attention more on these inputs, as shown by its "
            "lower mean entropy."
        )
    return {
        "runner": "fixed_reference_attention_v1",
        "seed": 0,
        "tokens": TOKENS,
        "tensor_shapes": {
            "Q": [len(QUERY), len(QUERY[0])],
            "K": [len(KEY), len(KEY[0])],
            "V": [len(VALUE), len(VALUE[0])],
            "QKᵀ scores": [len(QUERY), len(KEY)],
            "attention weights": [len(QUERY), len(KEY)],
            "output": [len(QUERY), len(VALUE[0])],
        },
        "inputs": {"Q": _rounded(QUERY), "K": _rounded(KEY), "V": _rounded(VALUE)},
        "variants": [scaled, user_variant],
        "user_score_divisor": score_divisor,
        "interpretation": interpretation,
        "limitation": (
            "This is a tiny deterministic teaching example, not a reproduction of the paper's "
            "training or benchmark results. Generated project code is not executed."
        ),
    }


def _softmax_metrics(raw_scores: list[list[float]], divisor: float) -> tuple[dict[str, float], list[float]]:
    logits = [[score / divisor for score in row] for row in raw_scores]
    probabilities: list[list[float]] = []
    for row in logits:
        peak = max(row)
        exp_scores = [math.exp(score - peak) for score in row]
        total = sum(exp_scores)
        probabilities.append([score / total for score in exp_scores])

    entropies = [-sum(p * math.log(p) for p in row if p > 0) for row in probabilities]
    peaks = [max(row) for row in probabilities]
    flat_logits = [score for row in logits for score in row]
    mean_logit = sum(flat_logits) / len(flat_logits)
    logit_std = math.sqrt(sum((score - mean_logit) ** 2 for score in flat_logits) / len(flat_logits))
    key_count = len(probabilities[0])
    gradient_proxy = sum(p * (1 - p) for row in probabilities for p in row) / (
        len(probabilities) * key_count
    )
    mean_entropy = sum(entropies) / len(entropies)
    metrics = {
        "logit_std": round(logit_std, 5),
        "mean_entropy_nats": round(mean_entropy, 5),
        "normalized_entropy": round(mean_entropy / math.log(key_count), 5),
        "mean_max_probability": round(sum(peaks) / len(peaks), 5),
        "saturated_query_rate": round(sum(peak >= 0.95 for peak in peaks) / len(peaks), 5),
        "mean_softmax_gradient_proxy": round(gradient_proxy, 7),
    }
    return metrics, [round(value, 5) for value in probabilities[0]]


def run_claim_stress_test(dimensions: list[int], seed: int) -> dict[str, Any]:
    """Test scaled vs unscaled dot-product attention on paired synthetic Q/K samples.

    This is a bounded, deterministic teaching simulation. It does not execute project code
    or claim to reproduce trained Transformer results.
    """
    dims = sorted(set(dimensions))
    if len(dims) < 2 or len(dims) > 5 or any(d < 2 or d > 256 for d in dims):
        raise ValueError("Choose two to five unique key dimensions between 2 and 256.")
    if seed < 0 or seed > 2_147_483_647:
        raise ValueError("The random seed must be between 0 and 2147483647.")

    query_count = 24
    key_count = 12
    results: list[dict[str, Any]] = []
    largest_example: dict[str, Any] | None = None
    for dimension in dims:
        rng = random.Random(seed + dimension * 1_000_003)
        queries = [[rng.gauss(0.0, 1.0) for _ in range(dimension)] for _ in range(query_count)]
        keys = [[rng.gauss(0.0, 1.0) for _ in range(dimension)] for _ in range(key_count)]
        raw_scores = [
            [sum(q * k for q, k in zip(query, key, strict=True)) for key in keys]
            for query in queries
        ]
        paper_metrics, paper_example = _softmax_metrics(raw_scores, math.sqrt(dimension))
        unscaled_metrics, unscaled_example = _softmax_metrics(raw_scores, 1.0)
        results.append(
            {
                "key_dimension": dimension,
                "paper_scaled": paper_metrics,
                "unscaled": unscaled_metrics,
            }
        )
        if dimension == dims[-1]:
            largest_example = {
                "key_dimension": dimension,
                "paper_scaled": paper_example,
                "unscaled": unscaled_example,
            }

    high = results[-1]
    scaled_saturation = high["paper_scaled"]["saturated_query_rate"]
    unscaled_saturation = high["unscaled"]["saturated_query_rate"]
    if unscaled_saturation > scaled_saturation:
        interpretation = (
            f"At dₖ={dims[-1]}, {unscaled_saturation:.0%} of unscaled query rows crossed the "
            f"0.95 saturation threshold, compared with {scaled_saturation:.0%} after paper scaling. "
            "This run is consistent with the claim's proposed mechanism under the simulator's assumptions."
        )
    else:
        interpretation = (
            f"At dₖ={dims[-1]}, this seed did not produce a higher saturation rate for unscaled "
            "attention. Inspect the finite sample and try another seed; this small simulation can vary."
        )
    return {
        "runner": "paired_gaussian_attention_stress_v1",
        "seed": seed,
        "dimensions": dims,
        "query_count": query_count,
        "key_count": key_count,
        "saturation_threshold": 0.95,
        "results": results,
        "largest_dimension_example": largest_example,
        "interpretation": interpretation,
        "assumptions": [
            "Query and key components are independent samples from a standard normal distribution.",
            "Each key dimension uses 24 query vectors and 12 key vectors; the same dot products feed both variants.",
            "One attention head is simulated; learned projections, values, training, masking and residual layers are omitted.",
            "The softmax-gradient proxy is the mean diagonal derivative p(1-p), not a full Transformer training gradient.",
        ],
        "limitation": (
            "This experiment illustrates the scaling mechanism; it is not a reproduction of the paper's "
            "training, translation benchmarks, or trained model parameters."
        ),
    }
