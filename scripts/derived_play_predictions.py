"""Complete prediction history for score, total-goals and half/full-time plays."""

from __future__ import annotations

from typing import Any

from scripts.model_storage import store_model_prediction
from scripts.odds_conversion import expected_value, normalize_probabilities
from scripts.poisson_model import (
    derive_1x2,
    derive_total_goals,
    score_matrix,
)

DERIVED_PLAY_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "bf": ("market_baseline", "maher_poisson", "dixon_coles"),
    "zjq": ("market_baseline", "maher_poisson", "dixon_coles"),
    "bqc": ("market_baseline", "maher_poisson", "dixon_coles"),
}


def _latest_official_odds(
    conn: Any,
    match_id: int,
    predict_time: str,
) -> dict[str, dict[str, tuple[int, float]]]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (play_type, option_code)
                      id, play_type, option_code, sp_value
               FROM official_odds_snapshots
               WHERE match_id = %s
                 AND play_type IN ('bf', 'zjq', 'bqc')
                 AND is_open = true
                 AND sp_value > 0
                 AND snapshot_time <= %s
               ORDER BY play_type, option_code, snapshot_time DESC, id DESC""",
            (match_id, predict_time),
        )
        rows = cur.fetchall()

    odds: dict[str, dict[str, tuple[int, float]]] = {}
    for snapshot_id, play_type, option_code, sp_value in rows:
        odds.setdefault(str(play_type), {})[str(option_code)] = (
            int(snapshot_id),
            float(sp_value),
        )
    return odds


def _total_goals_probabilities(matrix: dict[str, float]) -> dict[str, float]:
    probabilities = derive_total_goals(matrix)
    probabilities["7"] = probabilities.pop("7+", 0.0)
    return probabilities


def _score_probabilities(
    matrix: dict[str, float],
    official_options: set[str],
) -> dict[str, float]:
    exact_options = {option for option in official_options if ":" in option}
    result: dict[str, float] = {}
    for option in official_options:
        if option in exact_options:
            result[option] = matrix.get(option, 0.0)
            continue
        if option not in {"other_h", "other_d", "other_a"}:
            result[option] = 0.0
            continue
        probability = 0.0
        for score, value in matrix.items():
            if score in exact_options:
                continue
            home_goals, away_goals = map(int, score.split(":"))
            if option == "other_h" and home_goals > away_goals:
                probability += value
            elif option == "other_d" and home_goals == away_goals:
                probability += value
            elif option == "other_a" and home_goals < away_goals:
                probability += value
        result[option] = probability
    return result


def _half_full_probabilities(
    matrix: dict[str, float],
    lambdas: tuple[float, float],
) -> dict[str, float]:
    home_lambda, away_lambda = lambdas
    half_time = derive_1x2(
        score_matrix(home_lambda * 0.45, away_lambda * 0.45, max_goals=4)
    )
    full_time = derive_1x2(matrix)
    return {
        f"{half_code}{full_code}": half_time[half_code] * full_time[full_code]
        for half_code in ("3", "1", "0")
        for full_code in ("3", "1", "0")
    }


def _derive_probabilities(
    play_type: str,
    matrix: dict[str, float],
    lambdas: tuple[float, float],
    official_options: set[str],
) -> dict[str, float]:
    if play_type == "zjq":
        return _total_goals_probabilities(matrix)
    if play_type == "bf":
        return _score_probabilities(matrix, official_options)
    return _half_full_probabilities(matrix, lambdas)


def _model_std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def store_derived_play_predictions(
    *,
    conn: Any,
    match_id: int,
    active_models: dict[str, int],
    raw_poisson_matrix: dict[str, float],
    poisson_matrix: dict[str, float],
    raw_dc_matrix: dict[str, float],
    dc_matrix: dict[str, float],
    raw_lambdas: tuple[float, float],
    adjusted_lambdas: tuple[float, float],
    feature_snapshot_id: int | None,
    predict_time: str,
) -> int:
    """Store unfiltered model history for every open official derived option."""
    official_odds = _latest_official_odds(conn, match_id, predict_time)
    stored = 0

    for play_type, option_odds in official_odds.items():
        capabilities = DERIVED_PLAY_CAPABILITIES.get(play_type, ())
        if not capabilities:
            continue
        official_options = set(option_odds)
        sp_values = {option: value[1] for option, value in option_odds.items()}
        market_probabilities = normalize_probabilities(sp_values)
        model_probabilities = {
            "market_baseline": (market_probabilities, market_probabilities),
            "maher_poisson": (
                _derive_probabilities(
                    play_type, raw_poisson_matrix, raw_lambdas, official_options
                ),
                _derive_probabilities(
                    play_type, poisson_matrix, adjusted_lambdas, official_options
                ),
            ),
            "dixon_coles": (
                _derive_probabilities(play_type, raw_dc_matrix, raw_lambdas, official_options),
                _derive_probabilities(play_type, dc_matrix, adjusted_lambdas, official_options),
            ),
        }

        for option_code, (snapshot_id, sp_value) in option_odds.items():
            disagreement = _model_std([
                model_probabilities[model_name][1].get(option_code, 0.0)
                for model_name in capabilities
                if active_models.get(model_name) is not None
            ])
            market_probability = market_probabilities.get(option_code, 0.0)
            for model_name in capabilities:
                model_version_id = active_models.get(model_name)
                if model_version_id is None:
                    continue
                raw_probabilities, adjusted_probabilities = model_probabilities[model_name]
                raw_probability = raw_probabilities.get(option_code, 0.0)
                model_probability = adjusted_probabilities.get(option_code, 0.0)
                fair_odds = 1.0 / model_probability if model_probability > 0 else None
                store_model_prediction(
                    conn,
                    {
                        "match_id": match_id,
                        "model_version_id": model_version_id,
                        "odds_snapshot_id": snapshot_id,
                        "feature_snapshot_id": feature_snapshot_id,
                        "predict_time": predict_time,
                        "play_type": play_type,
                        "option_code": option_code,
                        "raw_model_probability": round(raw_probability, 6),
                        "model_probability": round(model_probability, 6),
                        "market_probability": round(market_probability, 6),
                        "probability_lower_bound": round(
                            max(0.0, model_probability - disagreement * 2), 6
                        ),
                        "probability_upper_bound": round(
                            min(1.0, model_probability + disagreement * 2), 6
                        ),
                        "uncertainty_score": round(disagreement, 6),
                        "adjusted_probability": round(model_probability, 6),
                        "fair_odds": round(fair_odds, 4) if fair_odds else None,
                        "ev": round(expected_value(model_probability, sp_value), 6),
                        "confidence_score": round(max(0.0, 1.0 - disagreement * 3), 4),
                        "risk_score": round(min(1.0, disagreement * 3), 4),
                        "uncertainty_reason": {
                            "derived_from": "official_market"
                            if model_name == "market_baseline"
                            else "score_matrix",
                            "model_capability": play_type,
                            "recommendation_filtered": False,
                            "feature_adjustment": {
                                "applied": abs(raw_probability - model_probability) > 1e-9,
                                "snapshot_id": feature_snapshot_id,
                            },
                        },
                    },
                )
                stored += 1
    return stored
