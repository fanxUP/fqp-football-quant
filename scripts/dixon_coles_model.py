"""Dixon-Coles低比分修正骨架。
注意：rho需要通过历史数据最大似然估计。"""

from __future__ import annotations

from scripts.poisson_model import score_matrix


def dc_tau(
    home_goals: int, away_goals: int, lambda_home: float, lambda_away: float, rho: float
) -> float:
    if home_goals == 0 and away_goals == 0:
        return 1 - (lambda_home * lambda_away * rho)
    if home_goals == 0 and away_goals == 1:
        return 1 + (lambda_home * rho)
    if home_goals == 1 and away_goals == 0:
        return 1 + (lambda_away * rho)
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


def dixon_coles_matrix(
    lambda_home: float, lambda_away: float, rho: float, max_goals: int = 7
) -> dict[str, float]:
    base = score_matrix(lambda_home, lambda_away, max_goals=max_goals)
    adjusted = {}
    for score, p in base.items():
        h, a = map(int, score.split(":"))
        adjusted[score] = max(0.0, p * dc_tau(h, a, lambda_home, lambda_away, rho))
    s = sum(adjusted.values())
    return {k: v / s for k, v in adjusted.items()}
