from __future__ import annotations

import pytest

from app.services.projects.experiment_runner import run_claim_stress_test


def test_paper_scaling_controls_logit_scale_and_softmax_saturation() -> None:
    run = run_claim_stress_test([4, 16, 64, 256], seed=42)
    low, high = run["results"][0], run["results"][-1]

    assert high["unscaled"]["logit_std"] > high["paper_scaled"]["logit_std"] * 10
    assert high["unscaled"]["saturated_query_rate"] > high["paper_scaled"]["saturated_query_rate"]
    assert high["unscaled"]["normalized_entropy"] < high["paper_scaled"]["normalized_entropy"]
    assert high["unscaled"]["mean_softmax_gradient_proxy"] < high["paper_scaled"]["mean_softmax_gradient_proxy"]
    assert low["paper_scaled"]["saturated_query_rate"] == 0
    assert run["largest_dimension_example"]["key_dimension"] == 256


def test_stress_test_is_reproducible_for_a_seed_and_changes_with_seed() -> None:
    first = run_claim_stress_test([8, 64, 256], seed=31)
    repeat = run_claim_stress_test([256, 8, 64], seed=31)
    changed = run_claim_stress_test([8, 64, 256], seed=32)

    assert first == repeat
    assert first != changed


@pytest.mark.parametrize(
    ("dimensions", "seed"),
    [([4], 0), ([4, 4], 0), ([4, 512], 0), ([4, 16], -1)],
)
def test_stress_test_rejects_unbounded_or_unpaired_inputs(dimensions: list[int], seed: int) -> None:
    with pytest.raises(ValueError):
        run_claim_stress_test(dimensions, seed)
