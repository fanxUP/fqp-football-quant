from scripts.news_shadow_model import MAX_PROBABILITY_SHIFT, adjust_probabilities, score_prediction


def test_positive_home_news_increases_home_probability_with_bounded_shift() -> None:
    baseline = {"3": 0.45, "1": 0.30, "0": 0.25}

    adjusted = adjust_probabilities(baseline, home_impact=0.9, away_impact=-0.7)

    assert adjusted["3"] > baseline["3"]
    assert adjusted["0"] < baseline["0"]
    assert adjusted["3"] - baseline["3"] <= MAX_PROBABILITY_SHIFT + 1e-9
    assert round(sum(adjusted.values()), 9) == 1.0


def test_neutral_news_keeps_probabilities_unchanged() -> None:
    baseline = {"3": 0.4, "1": 0.35, "0": 0.25}

    assert adjust_probabilities(baseline, 0, 0) == baseline


def test_prediction_scores_are_comparable_for_same_actual_result() -> None:
    baseline = score_prediction({"3": 0.4, "1": 0.3, "0": 0.3}, "3")
    improved = score_prediction({"3": 0.5, "1": 0.25, "0": 0.25}, "3")

    assert improved["brier"] < baseline["brier"]
    assert improved["logLoss"] < baseline["logLoss"]
