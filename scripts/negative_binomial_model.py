"""Over-dispersed score distribution for shadow-only football evaluation."""

from __future__ import annotations

from collections.abc import Iterable
from math import exp, lgamma, log
from statistics import fmean, variance


def _validate(mean: float, dispersion: float) -> None:
    if mean <= 0:
        raise ValueError("goal mean must be positive")
    if dispersion <= 0:
        raise ValueError("dispersion must be positive")


def negative_binomial_pmf(goals: int, mean: float, dispersion: float) -> float:
    """Return NB2 probability where variance equals mean + mean² / dispersion."""
    _validate(mean, dispersion)
    if goals < 0:
        return 0.0
    return exp(
        lgamma(goals + dispersion)
        - lgamma(dispersion)
        - lgamma(goals + 1)
        + dispersion * log(dispersion / (dispersion + mean))
        + goals * log(mean / (dispersion + mean))
    )


def negative_binomial_score_matrix(
    lambda_home: float, lambda_away: float, dispersion: float, max_goals: int = 7
) -> dict[str, float]:
    """Return a normalized finite score matrix with separate home/away NB2 goals."""
    _validate(lambda_home, dispersion)
    _validate(lambda_away, dispersion)
    matrix = {
        f"{home_goals}:{away_goals}": (
            negative_binomial_pmf(home_goals, lambda_home, dispersion)
            * negative_binomial_pmf(away_goals, lambda_away, dispersion)
        )
        for home_goals in range(max_goals + 1)
        for away_goals in range(max_goals + 1)
    }
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}


def fit_goal_dispersion(goal_counts: Iterable[int], minimum_samples: int = 100) -> float | None:
    """Fit one reviewable global NB2 dispersion from official settled goal counts."""
    values = [int(value) for value in goal_counts if int(value) >= 0]
    if len(values) < minimum_samples:
        return None
    mean = fmean(values)
    observed_variance = variance(values)
    if mean <= 0 or observed_variance <= mean:
        return None
    return max(0.05, min(100.0, mean * mean / (observed_variance - mean)))
