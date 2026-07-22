import pytest

from scripts.upset.hypotheses import (
    can_transition,
    evaluate_validation_metrics,
    promotion_requirements_met,
)


def test_hypothesis_state_machine_is_ordered():
    assert can_transition("research_only", "backtesting") is True
    assert can_transition("backtesting", "out_of_sample") is True
    assert can_transition("research_only", "promoted") is False
    assert can_transition("promoted", "research_only") is False


def test_feature_promotion_requires_three_independent_validations():
    passed = {"backtest": True, "out_of_sample": True, "simulation": True}
    assert promotion_requirements_met(passed) is True
    assert promotion_requirements_met({**passed, "simulation": False}) is False
    assert promotion_requirements_met({"backtest": True}) is False


def test_unknown_transition_is_rejected():
    with pytest.raises(ValueError, match="未知研究状态"):
        can_transition("draft", "backtesting")


def test_backtest_metrics_are_checked_against_explicit_thresholds():
    passed, reasons = evaluate_validation_metrics(
        {"n_bets": 120, "roi": 0.08, "brier_score": 0.21, "max_drawdown_pct": 0.12},
        {"min_bets": 100, "min_roi": 0.03, "max_brier": 0.25, "max_drawdown_pct": 0.2},
    )
    assert passed is True
    assert reasons == []

    passed, reasons = evaluate_validation_metrics(
        {"n_bets": 20, "roi": -0.02, "brier_score": 0.31, "max_drawdown_pct": 0.4},
        {"min_bets": 100, "min_roi": 0.03, "max_brier": 0.25, "max_drawdown_pct": 0.2},
    )
    assert passed is False
    assert set(reasons) == {
        "INSUFFICIENT_SAMPLE",
        "ROI_BELOW_THRESHOLD",
        "BRIER_TOO_HIGH",
        "DRAWDOWN_TOO_HIGH",
    }
