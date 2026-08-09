"""Shared-goal bivariate Poisson score distribution.

The marginal expected goals remain the Maher rates.  A non-negative shared
component captures score correlation while preserving those marginals.
"""

from __future__ import annotations

from math import exp, factorial


def _validate_rates(lambda_home: float, lambda_away: float, shared_goal_component: float) -> None:
    if lambda_home <= 0 or lambda_away <= 0:
        raise ValueError("goal rates must be positive")
    if not 0 <= shared_goal_component < min(lambda_home, lambda_away):
        raise ValueError("shared_goal_component must be non-negative and below both goal rates")


def bivariate_score_probability(
    home_goals: int,
    away_goals: int,
    lambda_home: float,
    lambda_away: float,
    shared_goal_component: float,
) -> float:
    """Return P(home_goals, away_goals) for a shared-goal Poisson process."""
    _validate_rates(lambda_home, lambda_away, shared_goal_component)
    if home_goals < 0 or away_goals < 0:
        return 0.0
    independent_home = lambda_home - shared_goal_component
    independent_away = lambda_away - shared_goal_component
    probability = 0.0
    for shared_goals in range(min(home_goals, away_goals) + 1):
        probability += (
            independent_home ** (home_goals - shared_goals)
            / factorial(home_goals - shared_goals)
            * independent_away ** (away_goals - shared_goals)
            / factorial(away_goals - shared_goals)
            * shared_goal_component**shared_goals
            / factorial(shared_goals)
        )
    return exp(-(lambda_home + lambda_away - shared_goal_component)) * probability


def bivariate_score_matrix(
    lambda_home: float,
    lambda_away: float,
    shared_goal_component: float,
    max_goals: int = 7,
) -> dict[str, float]:
    """Return a normalized finite bivariate Poisson score matrix."""
    _validate_rates(lambda_home, lambda_away, shared_goal_component)
    matrix = {
        f"{home_goals}:{away_goals}": bivariate_score_probability(
            home_goals,
            away_goals,
            lambda_home,
            lambda_away,
            shared_goal_component,
        )
        for home_goals in range(max_goals + 1)
        for away_goals in range(max_goals + 1)
    }
    total = sum(matrix.values())
    return {score: probability / total for score, probability in matrix.items()}
