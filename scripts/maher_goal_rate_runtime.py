"""Shared, odds-independent Maher goal-rate loading for existing model paths."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

MIN_MAHER_MATCHES = 5


@dataclass(frozen=True)
class TrainedGoalRates:
    home_lambda: float
    away_lambda: float
    minimum_team_matches: int
    training_matches: int


def load_trained_goal_rates(
    model_parameters: dict[str, dict[str, Any]],
    feature_snapshot: dict[str, Any] | None,
) -> TrainedGoalRates | None:
    """Build independent goal rates from a converged historical Maher fit."""
    parameters = model_parameters.get("maher_poisson")
    if (
        not isinstance(parameters, dict)
        or parameters.get("converged") is not True
        or not feature_snapshot
    ):
        return None
    home_team_id = feature_snapshot.get("home_team_id")
    away_team_id = feature_snapshot.get("away_team_id")
    if not home_team_id or not away_team_id:
        return None

    home_key = str(home_team_id)
    away_key = str(away_team_id)
    attack = parameters.get("attack") or {}
    defense = parameters.get("defense") or {}
    match_counts = parameters.get("team_match_counts") or {}
    if not all(isinstance(value, dict) for value in (attack, defense, match_counts)):
        return None
    required_keys = (home_key, away_key)
    if any(
        key not in attack or key not in defense or key not in match_counts for key in required_keys
    ):
        return None
    try:
        minimum_team_matches = min(int(match_counts[home_key]), int(match_counts[away_key]))
        if minimum_team_matches < MIN_MAHER_MATCHES:
            return None
        home_lambda = math.exp(
            float(attack[home_key])
            + float(defense[away_key])
            + float(parameters.get("home_advantage", 0.0))
            + float(parameters.get("league_intercept", 0.0))
        )
        away_lambda = math.exp(
            float(attack[away_key])
            + float(defense[home_key])
            + float(parameters.get("league_intercept", 0.0))
        )
        training_matches = int(parameters.get("n_matches") or 0)
    except TypeError, ValueError, OverflowError:
        return None
    if not all(
        math.isfinite(value) and 0.05 <= value <= 8.0 for value in (home_lambda, away_lambda)
    ):
        return None
    return TrainedGoalRates(
        home_lambda=home_lambda,
        away_lambda=away_lambda,
        minimum_team_matches=minimum_team_matches,
        training_matches=training_matches,
    )
