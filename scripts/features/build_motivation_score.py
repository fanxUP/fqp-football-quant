"""战意/动力评分特征构建器。

纯规则引擎，无需外部 API。从 season_standings_snapshots 读取积分榜，
结合 motivation_rules.yaml 配置计算每支球队的战意评分。

5-factor 加权公式:
  - objective_necessity (0.40): 保级/争冠/欧战需要的积分紧迫度
  - ranking_or_prize_value (0.15): 排名对应的奖金/荣誉价值
  - home_derby_revenge (0.15): 主场/德比/复仇动机
  - future_schedule_pressure_inverse (0.20): 后续赛程越轻松→当前越要拿分
  - lineup_commitment_signal (0.10): 首发阵容是否反映全力投入

修正项: must_win(+10), already_qualified(-15), already_eliminated(-10)

输出字段（写入 team_motivation_snapshots + match_feature_snapshots）:
  - home_motivation_score / away_motivation_score / motivation_diff
  - home_must_win / away_must_win
  - home_draw_enough / away_draw_enough
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.feature_storage import (
    get_latest_standings,
    store_team_motivation_snapshot,
)

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "motivation_rules.yaml"

_weights: dict[str, Any] | None = None


def _load_weights() -> dict[str, Any]:
    global _weights
    if _weights is None:
        with open(_CONFIG_PATH) as f:
            _weights = yaml.safe_load(f)
    return _weights


WEIGHTS = {
    "objective_necessity": 0.40,
    "ranking_or_prize_value": 0.15,
    "home_derby_revenge": 0.15,
    "future_schedule_pressure_inverse": 0.20,
    "lineup_commitment_signal": 0.10,
}


def compute_motivation_score(ctx: dict[str, Any]) -> float:
    """5-factor weighted motivation score (preserves original skeleton signature)."""
    objective = float(ctx.get("objective_necessity") or 0)
    ranking = float(ctx.get("ranking_or_prize_value") or 0)
    derby = float(ctx.get("home_derby_revenge") or 0)
    future = float(ctx.get("future_schedule_pressure_inverse") or 0)
    lineup = float(ctx.get("lineup_commitment_signal") or 0)

    score = (
        objective * WEIGHTS["objective_necessity"]
        + ranking * WEIGHTS["ranking_or_prize_value"]
        + derby * WEIGHTS["home_derby_revenge"]
        + future * WEIGHTS["future_schedule_pressure_inverse"]
        + lineup * WEIGHTS["lineup_commitment_signal"]
    )

    if ctx.get("must_win"):
        score += 10
    if ctx.get("already_qualified"):
        score -= 15
    if ctx.get("already_eliminated"):
        score -= 10

    return max(0.0, min(100.0, score))


def _compute_motivation_from_standings(
    team_id: int,
    standings: list[dict],
    total_teams: int,
    is_home: bool,
    is_derby: bool,
) -> dict[str, Any]:
    """Compute motivation context from standings data.

    Args:
        team_id: Team's internal ID.
        standings: List of all team standings rows.
        total_teams: Total number of teams in the competition.
        is_home: Whether this team is the home team.
        is_derby: Whether this is a derby match.

    Returns:
        Motivation context dict for compute_motivation_score().
    """
    # Find this team in standings
    team_row = None
    for row in standings:
        if row["team_id"] == team_id:
            team_row = row
            break

    if not team_row:
        return {
            "objective_necessity": 50,
            "ranking_or_prize_value": 50,
            "home_derby_revenge": 70 if is_derby else (55 if is_home else 40),
            "future_schedule_pressure_inverse": 50,
            "lineup_commitment_signal": 50,
            "must_win": False,
            "already_qualified": False,
            "already_eliminated": False,
        }

    rank = team_row.get("rank") or (total_teams // 2)
    points = team_row.get("points") or 0
    played = team_row.get("played") or 0
    remaining = max(1, 38 - played)

    # --- Objective necessity ---
    # Top 4 race: need ~75 points for CL in top leagues
    # Relegation: need ~36 points for safety
    # Points per game and projected final points
    ppg = points / max(1, played)
    points + ppg * remaining

    relegation_zone = total_teams - 3  # bottom 3
    cl_zone = 4  # top 4
    title_zone = 1  # top 1

    necessity = 50.0  # neutral

    if rank <= title_zone:
        # Title race: high motivation to stay on top
        necessity = 85.0
    elif rank <= cl_zone:
        # CL race: need to defend position
        gap_to_5th = 0
        for r in standings:
            if r.get("rank") == cl_zone + 1:
                gap_to_5th = points - r.get("points", 0)
                break
        if gap_to_5th <= 5:
            necessity = 80.0
        else:
            necessity = 60.0
    elif rank >= relegation_zone:
        # Relegation battle: high pressure
        gap = 0
        for r in standings:
            if r.get("rank") == relegation_zone - 1:
                gap = r.get("points", 0) - points
                break
        necessity = min(95.0, 60.0 + max(0, 4 - gap) * 10.0)
    else:
        # Mid-table
        necessity = 40.0

    # --- Ranking/prize value ---
    # Higher rank = more prize money
    prize = max(30.0, 80.0 - rank * (50.0 / total_teams))

    # --- Derby/Home/Revenge ---
    derby_home = 70.0 if is_derby else (60.0 if is_home else 45.0)

    # --- Future schedule pressure (inverse) ---
    future_pressure = 50.0  # neutral; would need future opponent data

    # --- Lineup commitment ---
    lineup_commitment = 60.0  # assume normal commitment

    # --- Modifiers ---
    must_win = necessity > 75
    already_qualified = False
    already_eliminated = False

    # Cup group stage: check if mathematically eliminated
    if remaining <= 3 and ppg < 0.5 and rank > total_teams - 3:
        already_eliminated = True
    if remaining <= 3 and rank == 1 and points > 0:
        # Dominant lead = already qualified but still fighting for seeding
        pass

    return {
        "objective_necessity": necessity,
        "ranking_or_prize_value": prize,
        "home_derby_revenge": derby_home,
        "future_schedule_pressure_inverse": future_pressure,
        "lineup_commitment_signal": lineup_commitment,
        "must_win": must_win,
        "already_qualified": already_qualified,
        "already_eliminated": already_eliminated,
    }


def build_motivation_features(
    conn: Any,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
    competition_season_id: int | None = None,
    is_derby: bool = False,
    total_teams: int = 20,
) -> dict[str, Any]:
    """Build motivation features for a match.

    Args:
        conn: DB connection.
        match_id: Match ID.
        home_team_id: Home team internal ID.
        away_team_id: Away team internal ID.
        competition_season_id: Competition season ID for standings lookup.
        is_derby: Whether this is a derby match.
        total_teams: Total teams in the league (default 20).

    Returns:
        Dict with motivation fields for snapshot assembly.
    """
    home_score = None
    away_score = None
    home_must_win = None
    away_must_win = None
    home_draw_enough = None
    away_draw_enough = None

    # Get standings if available
    standings = []
    if competition_season_id:
        try:
            standings = get_latest_standings(conn, competition_season_id)
        except Exception as e:
            print(f"[motivation] standings error: {e}")
    standings_team_ids = {row.get("team_id") for row in standings}

    snapshot_time = __import__("datetime").datetime.now().isoformat(timespec="seconds")

    # Home team
    if home_team_id and home_team_id in standings_team_ids:
        try:
            ctx = _compute_motivation_from_standings(
                home_team_id, standings, total_teams, is_home=True, is_derby=is_derby
            )
            home_score = compute_motivation_score(ctx)
            home_must_win = ctx["must_win"]
            home_draw_enough = home_score < 60 and ctx.get("objective_necessity", 50) < 60

            # Store
            store_team_motivation_snapshot(
                conn,
                {
                    "match_id": match_id,
                    "team_id": home_team_id,
                    "competition_season_id": competition_season_id,
                    "snapshot_time": snapshot_time,
                    "final_motivation_score": home_score,
                    "must_win": home_must_win,
                    "draw_enough": home_draw_enough,
                    "already_qualified": ctx.get("already_qualified", False),
                    "already_eliminated": ctx.get("already_eliminated", False),
                    "raw_json": ctx,
                    "motivation_reason": ctx,
                },
            )
        except Exception as e:
            print(f"[motivation] error home team {home_team_id}: {e}")

    # Away team
    if away_team_id and away_team_id in standings_team_ids:
        try:
            ctx = _compute_motivation_from_standings(
                away_team_id, standings, total_teams, is_home=False, is_derby=is_derby
            )
            away_score = compute_motivation_score(ctx)
            away_must_win = ctx["must_win"]
            away_draw_enough = away_score < 60 and ctx.get("objective_necessity", 50) < 60

            store_team_motivation_snapshot(
                conn,
                {
                    "match_id": match_id,
                    "team_id": away_team_id,
                    "competition_season_id": competition_season_id,
                    "snapshot_time": snapshot_time,
                    "final_motivation_score": away_score,
                    "must_win": away_must_win,
                    "draw_enough": away_draw_enough,
                    "already_qualified": ctx.get("already_qualified", False),
                    "already_eliminated": ctx.get("already_eliminated", False),
                    "raw_json": ctx,
                    "motivation_reason": ctx,
                },
            )
        except Exception as e:
            print(f"[motivation] error away team {away_team_id}: {e}")

    covered_team_count = int(home_team_id in standings_team_ids) + int(
        away_team_id in standings_team_ids
    )
    has_motivation = home_score is not None and away_score is not None and covered_team_count == 2

    return {
        "home_motivation_score": home_score,
        "away_motivation_score": away_score,
        "motivation_diff": (
            round((home_score or 0) - (away_score or 0), 4)
            if home_score is not None and away_score is not None
            else None
        ),
        "home_must_win": home_must_win,
        "away_must_win": away_must_win,
        "home_draw_enough": home_draw_enough,
        "away_draw_enough": away_draw_enough,
        "has_motivation_data": has_motivation,
        "covered_team_count": covered_team_count,
        "used_default_estimate": covered_team_count < 2,
    }
