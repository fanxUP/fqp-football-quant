import pytest

from scripts.feature_adjustment import adjust_goal_rates


def test_feature_adjustment_is_disabled_without_a_qualified_snapshot() -> None:
    result = adjust_goal_rates(1.4, 1.1, None)

    assert result.home_lambda == 1.4
    assert result.away_lambda == 1.1
    assert result.applied is False
    assert result.reasons == []


def test_feature_adjustment_changes_goal_rates_and_records_reasons() -> None:
    snapshot = {
        "id": 88,
        "data_completeness_score": 70,
        "lineup_strength_diff": 20,
        "absence_impact_diff": -10,
        "rest_days_diff": 2,
        "motivation_diff": 15,
        "rotation_risk_diff": -5,
        "goal_expectation_weather_adjustment": -0.03,
    }

    result = adjust_goal_rates(1.4, 1.1, snapshot)

    assert result.applied is True
    assert result.home_lambda > 1.4 * 0.97
    assert result.away_lambda < 1.1 * 0.97
    assert result.total_goal_multiplier == pytest.approx(0.97)
    assert {item["feature"] for item in result.reasons} == {
        "lineup_strength_diff",
        "absence_impact_diff",
        "rest_days_diff",
        "motivation_diff",
        "rotation_risk_diff",
        "goal_expectation_weather_adjustment",
    }


def test_feature_adjustment_is_bounded_for_extreme_inputs() -> None:
    result = adjust_goal_rates(
        1.4,
        1.1,
        {
            "data_completeness_score": 100,
            "lineup_strength_diff": 999,
            "absence_impact_diff": -999,
            "rest_days_diff": 999,
            "motivation_diff": 999,
        },
    )

    assert result.home_log_shift == pytest.approx(0.15)
    assert 0.2 <= result.home_lambda <= 4.5
    assert 0.2 <= result.away_lambda <= 4.5
