"""Glicko-2 评分与赛前概率的行为约束。"""

from scripts.glicko2_model import Glicko2Rating, predict_1x2, update_rating_period


def test_glicko2_home_win_improves_rating_and_reduces_uncertainty() -> None:
    home = Glicko2Rating(rating=1500.0, deviation=350.0, volatility=0.06, matches_played=0)
    away = Glicko2Rating(rating=1500.0, deviation=350.0, volatility=0.06, matches_played=0)

    updated_home, updated_away = update_rating_period(home, away, home_score=1.0)

    assert updated_home.rating > home.rating
    assert updated_away.rating < away.rating
    assert updated_home.deviation < home.deviation
    assert updated_away.deviation < away.deviation
    assert updated_home.matches_played == 1
    assert updated_away.matches_played == 1


def test_glicko2_prediction_is_normalized_and_accounts_for_home_advantage() -> None:
    probabilities = predict_1x2(
        Glicko2Rating(rating=1500.0, deviation=45.0, volatility=0.06, matches_played=20),
        Glicko2Rating(rating=1500.0, deviation=45.0, volatility=0.06, matches_played=20),
    )

    assert round(sum(probabilities.values()), 10) == 1.0
    assert probabilities["3"] > probabilities["0"]
    assert 0.08 <= probabilities["1"] <= 0.38


def test_glicko2_high_uncertainty_reduces_strength_gap() -> None:
    confident = predict_1x2(
        Glicko2Rating(rating=1700.0, deviation=40.0, volatility=0.06, matches_played=30),
        Glicko2Rating(rating=1500.0, deviation=40.0, volatility=0.06, matches_played=30),
    )
    uncertain = predict_1x2(
        Glicko2Rating(rating=1700.0, deviation=200.0, volatility=0.06, matches_played=30),
        Glicko2Rating(rating=1500.0, deviation=200.0, volatility=0.06, matches_played=30),
    )

    assert confident["3"] > uncertain["3"]
