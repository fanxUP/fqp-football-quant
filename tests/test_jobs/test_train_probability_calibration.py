from __future__ import annotations

import pytest

from scripts.jobs.train_probability_calibration import fit_profiles_from_prediction_rows


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, -0.1, 1.1, None])
def test_bad_match_does_not_cancel_clean_model_samples(bad):
    rows = [
        ("elo", mid, code, probability, "3", f"2026-08-{mid:02d}")
        for mid in range(1, 6)
        for code, probability in (("3", 0.6), ("1", 0.3), ("0", 0.1))
    ]
    rows += [
        ("elo", 6, code, probability, "3", "2026-08-06")
        for code, probability in (("3", bad), ("1", 0.3), ("0", 0.1))
    ]
    profiles = fit_profiles_from_prediction_rows(
        rows, minimum_samples=2, minimum_validation_samples=1
    )
    assert len(profiles) == 1
    assert profiles[0]["training_sample_count"] + profiles[0]["validation_sample_count"] == 5


def test_conflicting_group_is_not_accepted_using_last_row_wins():
    rows = [
        ("elo", 1, code, probability, "3", "2026-08-01")
        for code, probability in (("3", 0.6), ("1", 0.3), ("0", 0.1))
    ]
    rows += [("elo", 1, "3", 0.6, "0", "2026-08-01")]
    assert (
        fit_profiles_from_prediction_rows(rows, minimum_samples=0, minimum_validation_samples=0)
        == []
    )


def test_profile_fitting_groups_complete_settled_match_distributions_by_model() -> None:
    rows = []
    outcomes = ["3", "1", "0", "3", "3", "1"]
    for match_id, actual in enumerate(outcomes, start=1):
        for option_code, probability in (("3", 0.80), ("1", 0.12), ("0", 0.08)):
            rows.append(
                (
                    "elo_rating",
                    match_id,
                    option_code,
                    probability,
                    actual,
                    f"2026-08-{match_id:02d}T20:00:00",
                )
            )

    profiles = fit_profiles_from_prediction_rows(
        rows,
        minimum_samples=4,
        minimum_validation_samples=2,
    )

    assert len(profiles) == 1
    assert profiles[0]["model_name"] == "elo_rating"
    assert profiles[0]["sample_count"] == 2
    assert profiles[0]["training_sample_count"] == 4
    assert profiles[0]["method_name"] == "temperature_scaling_temporal_holdout_v1"


def test_rejected_samples_are_counted_before_temporal_split():
    rows = [
        ("elo", mid, code, p, "3", f"2026-08-{mid:02d}")
        for mid in range(1, 7)
        for code, p in (("3", 0.6), ("1", 0.3), ("0", 0.1))
    ]
    rows += [("elo", 7, "3", 0.8, "3", "2026-08-07")]
    counts = {}
    profiles = fit_profiles_from_prediction_rows(
        rows, minimum_samples=4, minimum_validation_samples=2, diagnostics=counts
    )
    assert len(profiles) == 1
    assert counts == {
        "candidate_groups": 7,
        "valid_groups": 6,
        "rejected_groups": 1,
        "rejected_by_model": {"elo": 1},
    }
    assert profiles[0]["training_sample_count"] == 4
    assert profiles[0]["validation_sample_count"] == 2


def test_profile_fitting_skips_incomplete_and_invalid_probability_sets() -> None:
    rows = [
        ("elo_rating", 1, "3", 0.7, "3", "2026-08-01T20:00:00"),
        ("elo_rating", 1, "1", 0.2, "3", "2026-08-01T20:00:00"),
        ("elo_rating", 2, "3", 1.2, "3", "2026-08-02T20:00:00"),
        ("elo_rating", 2, "1", 0.0, "3", "2026-08-02T20:00:00"),
        ("elo_rating", 2, "0", -0.2, "3", "2026-08-02T20:00:00"),
    ]

    assert fit_profiles_from_prediction_rows(rows, minimum_samples=1) == []
