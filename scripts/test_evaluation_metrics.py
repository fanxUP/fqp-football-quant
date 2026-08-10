from __future__ import annotations

from scripts.evaluation_metrics import compute_match_metrics


def test_match_metrics_persists_selected_clv_against_true_closing_market() -> None:
    metrics = compute_match_metrics(
        {"3": 0.60, "1": 0.25, "0": 0.15},
        {"3": 0.50, "1": 0.28, "0": 0.22},
        "3",
        model_name="Elo",
        closing_market_probs={"3": 0.54, "1": 0.26, "0": 0.20},
        closing_odds={"3": 2.0, "1": 3.2, "0": 3.8},
    )

    assert metrics["option_code"] == "3"
    assert metrics["model_probability"] == 0.60
    assert metrics["market_probability"] == 0.50
    assert metrics["closing_market_probability"] == 0.54
    assert metrics["probability_gap"] == 0.06
    assert metrics["clv_score"] == 0.04
    assert metrics["official_sp"] == 2.0
    assert metrics["fair_odds"] == 1.6667
    assert metrics["ev"] == 0.2
