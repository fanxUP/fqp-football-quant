"""Safety tests for the Bayesian recent-form shadow model."""

from __future__ import annotations

from scripts.bayesian_form_model import probabilities_from_team_outcomes


def test_bayesian_form_combines_both_teams_and_preserves_1x2_mapping() -> None:
    probabilities = probabilities_from_team_outcomes(
        home_outcomes=["3", "3", "1", "3", "0", "3"],
        away_outcomes=["0", "0", "1", "0", "3", "0"],
    )

    assert probabilities is not None
    assert sum(probabilities.values()) == 1.0
    assert probabilities["3"] > probabilities["0"]


def test_bayesian_form_rejects_short_team_histories() -> None:
    assert (
        probabilities_from_team_outcomes(
            home_outcomes=["3"] * 5,
            away_outcomes=["0"] * 6,
        )
        is None
    )
