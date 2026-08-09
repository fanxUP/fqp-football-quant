from __future__ import annotations

import pytest

from scripts.probability_calibration import (
    apply_temperature_scaling,
    evaluate_temperature_scaling_temporal_holdout,
    fit_temperature_scaling,
)


def test_temperature_scaling_keeps_three_way_probability_distribution_normalized() -> None:
    calibrated = apply_temperature_scaling({"3": 0.70, "1": 0.20, "0": 0.10}, 1.5)

    assert sum(calibrated.values()) == pytest.approx(1.0)
    assert calibrated["3"] < 0.70
    assert calibrated["0"] > 0.10


def test_temperature_fit_softens_repeated_overconfident_wrong_predictions() -> None:
    samples = [
        ({"3": 0.90, "1": 0.05, "0": 0.05}, "0"),
        ({"3": 0.85, "1": 0.10, "0": 0.05}, "1"),
        ({"3": 0.80, "1": 0.10, "0": 0.10}, "0"),
        ({"3": 0.75, "1": 0.15, "0": 0.10}, "3"),
    ]

    profile = fit_temperature_scaling(samples, minimum_samples=4)

    assert profile is not None
    assert profile["temperature"] > 1.0
    assert profile["log_loss_after"] < profile["log_loss_before"]


def test_temperature_fit_refuses_insufficient_or_incomplete_match_distributions() -> None:
    assert fit_temperature_scaling([], minimum_samples=1) is None
    assert fit_temperature_scaling([({"3": 0.7, "1": 0.3}, "3")], minimum_samples=1) is None


def test_temporal_holdout_scores_the_fitted_temperature_on_later_matches() -> None:
    samples = [
        ({"3": 0.90, "1": 0.05, "0": 0.05}, "0"),
        ({"3": 0.85, "1": 0.10, "0": 0.05}, "1"),
        ({"3": 0.80, "1": 0.10, "0": 0.10}, "0"),
        ({"3": 0.75, "1": 0.15, "0": 0.10}, "3"),
        ({"3": 0.90, "1": 0.05, "0": 0.05}, "3"),
        ({"3": 0.85, "1": 0.10, "0": 0.05}, "3"),
    ]

    profile = evaluate_temperature_scaling_temporal_holdout(
        samples,
        minimum_training_samples=4,
        minimum_validation_samples=2,
    )

    assert profile is not None
    assert profile["method_name"] == "temperature_scaling_temporal_holdout_v1"
    assert profile["training_sample_count"] == 4
    assert profile["sample_count"] == 2
    assert profile["log_loss_after"] > profile["log_loss_before"]
