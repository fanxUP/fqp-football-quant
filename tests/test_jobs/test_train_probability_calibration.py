from __future__ import annotations

from scripts.jobs.train_probability_calibration import fit_profiles_from_prediction_rows


def test_profile_fitting_groups_complete_settled_match_distributions_by_model() -> None:
    rows = []
    outcomes = ["3", "1", "0", "3"]
    for match_id, actual in enumerate(outcomes, start=1):
        for option_code, probability in (("3", 0.80), ("1", 0.12), ("0", 0.08)):
            rows.append(("elo_rating", match_id, option_code, probability, actual))

    profiles = fit_profiles_from_prediction_rows(rows, minimum_samples=4)

    assert len(profiles) == 1
    assert profiles[0]["model_name"] == "elo_rating"
    assert profiles[0]["sample_count"] == 4
    assert profiles[0]["method_name"] == "temperature_scaling_v1"


def test_profile_fitting_skips_incomplete_and_invalid_probability_sets() -> None:
    rows = [
        ("elo_rating", 1, "3", 0.7, "3"),
        ("elo_rating", 1, "1", 0.2, "3"),
        ("elo_rating", 2, "3", 1.2, "3"),
        ("elo_rating", 2, "1", 0.0, "3"),
        ("elo_rating", 2, "0", -0.2, "3"),
    ]

    assert fit_profiles_from_prediction_rows(rows, minimum_samples=1) == []
