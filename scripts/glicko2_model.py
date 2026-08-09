"""Glicko-2 球队评分模型。

评分与不确定性（rating deviation）同步更新；赛前概率仅使用赛前状态，
并把不确定性较高的球队预测收缩到中性分布，避免新赛季数据稀疏时过度自信。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

RATING_CENTER = 1500.0
GLICKO2_SCALE = 173.7178
INITIAL_DEVIATION = 350.0
INITIAL_VOLATILITY = 0.06
MIN_DEVIATION = 30.0
MAX_DEVIATION = 350.0
HOME_ADVANTAGE = 55.0
TAU = 0.5
EPSILON = 1e-6


@dataclass(frozen=True)
class Glicko2Rating:
    rating: float = RATING_CENTER
    deviation: float = INITIAL_DEVIATION
    volatility: float = INITIAL_VOLATILITY
    matches_played: int = 0


def _to_mu(rating: float) -> float:
    return (rating - RATING_CENTER) / GLICKO2_SCALE


def _to_phi(deviation: float) -> float:
    return deviation / GLICKO2_SCALE


def _to_rating(mu: float) -> float:
    return RATING_CENTER + GLICKO2_SCALE * mu


def _to_deviation(phi: float) -> float:
    return max(MIN_DEVIATION, min(MAX_DEVIATION, GLICKO2_SCALE * phi))


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _expected(mu: float, opponent_mu: float, opponent_phi: float) -> float:
    exponent = -_g(opponent_phi) * (mu - opponent_mu)
    exponent = max(-700.0, min(700.0, exponent))
    return 1.0 / (1.0 + math.exp(exponent))


def _new_volatility(phi: float, delta: float, variance: float, volatility: float) -> float:
    """Solve Glicko-2's volatility equation by the published iterative method."""
    a = math.log(volatility * volatility)

    def objective(x: float) -> float:
        exp_x = math.exp(x)
        numerator = exp_x * (delta * delta - phi * phi - variance - exp_x)
        denominator = 2.0 * (phi * phi + variance + exp_x) ** 2
        return numerator / denominator - (x - a) / (TAU * TAU)

    if delta * delta > phi * phi + variance:
        upper = math.log(delta * delta - phi * phi - variance)
    else:
        step = 1
        upper = a - step * TAU
        while objective(upper) < 0.0:
            step += 1
            upper = a - step * TAU

    lower = a
    f_lower = objective(lower)
    f_upper = objective(upper)
    while abs(upper - lower) > EPSILON:
        candidate = lower + (lower - upper) * f_lower / (f_upper - f_lower)
        f_candidate = objective(candidate)
        if f_candidate * f_upper < 0.0:
            lower, f_lower = upper, f_upper
        else:
            f_lower /= 2.0
        upper, f_upper = candidate, f_candidate
    return max(0.02, min(0.12, math.exp(lower / 2.0)))


def _update_single(player: Glicko2Rating, opponent: Glicko2Rating, score: float) -> Glicko2Rating:
    mu = _to_mu(player.rating)
    phi = _to_phi(player.deviation)
    opponent_mu = _to_mu(opponent.rating)
    opponent_phi = _to_phi(opponent.deviation)
    g_value = _g(opponent_phi)
    expected = _expected(mu, opponent_mu, opponent_phi)
    variance = 1.0 / (g_value * g_value * expected * (1.0 - expected))
    delta = variance * g_value * (score - expected)
    volatility = _new_volatility(phi, delta, variance, player.volatility)
    phi_star = math.sqrt(phi * phi + volatility * volatility)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / variance)
    new_mu = mu + new_phi * new_phi * g_value * (score - expected)
    return Glicko2Rating(
        rating=round(_to_rating(new_mu), 4),
        deviation=round(_to_deviation(new_phi), 4),
        volatility=round(volatility, 6),
        matches_played=player.matches_played + 1,
    )


def update_rating_period(
    home: Glicko2Rating,
    away: Glicko2Rating,
    *,
    home_score: float,
) -> tuple[Glicko2Rating, Glicko2Rating]:
    """Use one settled match as a rating period while preserving pre-match state."""
    if home_score not in {0.0, 0.5, 1.0}:
        raise ValueError("home_score 必须为 0、0.5 或 1")
    return _update_single(home, away, home_score), _update_single(away, home, 1.0 - home_score)


def predict_1x2(home: Glicko2Rating, away: Glicko2Rating) -> dict[str, float]:
    """Convert Glicko-2 strength and uncertainty into a calibrated 1x2 distribution."""
    home_mu = _to_mu(home.rating + HOME_ADVANTAGE)
    away_mu = _to_mu(away.rating)
    expected_home = _expected(home_mu, away_mu, _to_phi(away.deviation))
    strength_gap = abs(expected_home - 0.5)
    draw_probability = 0.30 * math.exp(-strength_gap * strength_gap / (2.0 * 0.25 * 0.25))
    draw_probability = max(0.08, min(0.38, draw_probability))
    probabilities = {
        "3": expected_home - draw_probability / 2.0,
        "1": draw_probability,
        "0": 1.0 - expected_home - draw_probability / 2.0,
    }
    reliability = max(
        0.0,
        min(1.0, (MAX_DEVIATION - (home.deviation + away.deviation) / 2.0) / 220.0),
    )
    neutral = {"3": 1.0 / 3.0, "1": 1.0 / 3.0, "0": 1.0 / 3.0}
    adjusted = {
        option: reliability * probability + (1.0 - reliability) * neutral[option]
        for option, probability in probabilities.items()
    }
    total = sum(adjusted.values())
    return {option: adjusted[option] / total for option in ("3", "1", "0")}


def _row_to_rating(row: tuple[Any, ...] | None) -> Glicko2Rating:
    if not row:
        return Glicko2Rating()
    return Glicko2Rating(
        rating=float(row[0]),
        deviation=float(row[1]),
        volatility=float(row[2]),
        matches_played=int(row[3]),
    )


def get_or_create_glicko2(
    conn: Any, team_id: int, team_name: str, season: str | None
) -> Glicko2Rating:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT rating, rating_deviation, volatility, matches_played
               FROM team_glicko2_ratings
               WHERE team_id = %s AND season IS NOT DISTINCT FROM %s""",
            (team_id, season),
        )
        state = _row_to_rating(cur.fetchone())
        if state.matches_played:
            return state
        cur.execute(
            """INSERT INTO team_glicko2_ratings
               (team_id, team_name, season, rating, rating_deviation, volatility)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (team_id, season) DO NOTHING""",
            (team_id, team_name, season, state.rating, state.deviation, state.volatility),
        )
    return state


def update_glicko2_ratings(
    conn: Any,
    *,
    home_team_id: int,
    away_team_id: int,
    home_team_name: str,
    away_team_name: str,
    home_goals: int,
    away_goals: int,
    match_id: int,
    match_date: str | None,
    season: str | None,
) -> dict[str, Any]:
    """Persist one settled match, idempotently guarded by the update log."""
    home_before = get_or_create_glicko2(conn, home_team_id, home_team_name, season)
    away_before = get_or_create_glicko2(conn, away_team_id, away_team_name, season)
    home_score = 1.0 if home_goals > away_goals else 0.5 if home_goals == away_goals else 0.0
    home_after, away_after = update_rating_period(home_before, away_before, home_score=home_score)
    with conn.cursor() as cur:
        for team_id, state in ((home_team_id, home_after), (away_team_id, away_after)):
            cur.execute(
                """UPDATE team_glicko2_ratings SET
                       rating = %s, rating_deviation = %s, volatility = %s,
                       matches_played = %s, last_match_date = %s, updated_at = NOW()
                   WHERE team_id = %s AND season IS NOT DISTINCT FROM %s""",
                (
                    state.rating,
                    state.deviation,
                    state.volatility,
                    state.matches_played,
                    match_date,
                    team_id,
                    season,
                ),
            )
        cur.execute(
            """INSERT INTO glicko2_update_logs
               (match_id, home_team_id, away_team_id, home_rating_before, away_rating_before,
                home_deviation_before, away_deviation_before, home_rating_after, away_rating_after,
                home_deviation_after, away_deviation_after, home_goals, away_goals, season)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                match_id,
                home_team_id,
                away_team_id,
                home_before.rating,
                away_before.rating,
                home_before.deviation,
                away_before.deviation,
                home_after.rating,
                away_after.rating,
                home_after.deviation,
                away_after.deviation,
                home_goals,
                away_goals,
                season,
            ),
        )
    conn.commit()
    return {"match_id": match_id, "home_rating": home_after.rating, "away_rating": away_after.rating}
