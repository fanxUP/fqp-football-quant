"""赛制博弈与避强队风险特征构建器。

纯规则引擎，无需外部 API。从 tournament_group_scenarios 和 motivation 数据
计算赛制博弈特征：避强对手倾向、放水风险、晋级后轮换概率。

输出字段（写入 match_feature_snapshots）:
  - home_avoid_strong_opponent_score / away_avoid_strong_opponent_score
  - home_tanking_risk_score / away_tanking_risk_score
  - tournament_incentive_risk_score
"""

from __future__ import annotations

from typing import Any

from scripts.feature_storage import (
    get_motivation_for_match,
    store_tournament_incentive_snapshot,
)

WEIGHTS = {
    "rank_controllability": 0.25,
    "opponent_strength_gap_by_rank": 0.35,
    "qualification_safety": 0.20,
    "points_goal_difference_constraint": 0.10,
    "manager_rotation_tendency": 0.10,
}


def compute_avoid_strong_opponent_score(ctx: dict[str, Any]) -> float:
    """5-factor avoid-strong-opponent score (preserves original skeleton signature)."""
    score = 0.0
    for k, w in WEIGHTS.items():
        score += float(ctx.get(k) or 0) * w
    return max(0.0, min(100.0, score))


def compute_tanking_risk(ctx: dict[str, Any]) -> float:
    """Tanking/放水 risk score (preserves original skeleton signature)."""
    avoid_score = compute_avoid_strong_opponent_score(ctx)
    already_safe = 1.0 if ctx.get("already_qualified") else 0.0
    draw_enough = 1.0 if ctx.get("draw_enough") else 0.0
    must_win = 1.0 if ctx.get("must_win") else 0.0
    raw = avoid_score * 0.55 + already_safe * 25 + draw_enough * 15 - must_win * 25
    return max(0.0, min(100.0, raw))


def _build_context_from_motivation(mot: dict | None, is_cup: bool) -> dict[str, Any]:
    """Build tournament incentive context from motivation data.

    Args:
        mot: Motivation snapshot dict for the team.
        is_cup: Whether this is a cup/group stage tournament.

    Returns:
        Context dict for compute_avoid_strong_opponent_score / compute_tanking_risk.
    """
    if not mot:
        return {
            "rank_controllability": 50,
            "opponent_strength_gap_by_rank": 50,
            "qualification_safety": 50,
            "points_goal_difference_constraint": 50,
            "manager_rotation_tendency": 30,
            "already_qualified": False,
            "draw_enough": False,
            "must_win": False,
        }

    mot_score = float(mot.get("final_motivation_score") or 50)
    already_qualified = bool(mot.get("already_qualified"))
    already_eliminated = bool(mot.get("already_eliminated"))
    must_win = bool(mot.get("must_win"))
    draw_enough = bool(mot.get("draw_enough"))

    # Rank controllability: lower motivation = less control over rank outcome
    controllability = mot_score

    # Opponent strength gap: approximated from motivation pressure
    # Higher relegation pressure = likely facing stronger opponents
    relegation = float(mot.get("relegation_pressure_score") or 0)
    opponent_gap = 50.0 + (relegation - 50.0) * 0.5

    # Qualification safety
    if already_qualified:
        safety = 95.0
    elif already_eliminated:
        safety = 5.0
    elif must_win:
        safety = 20.0
    elif draw_enough:
        safety = 60.0
    else:
        safety = 50.0

    # Points/Goal difference constraint: neutral for league play
    points_constraint = 50.0

    # Manager rotation tendency: higher if already qualified
    rotation = 70.0 if already_qualified else (20.0 if must_win else 30.0)

    return {
        "rank_controllability": controllability,
        "opponent_strength_gap_by_rank": opponent_gap,
        "qualification_safety": safety,
        "points_goal_difference_constraint": points_constraint,
        "manager_rotation_tendency": rotation,
        "already_qualified": already_qualified,
        "draw_enough": draw_enough,
        "must_win": must_win,
    }


def build_tournament_incentive_features(
    conn: Any,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
    is_cup: bool = False,
) -> dict[str, Any]:
    """Build tournament incentive features for a match.

    Args:
        conn: DB connection.
        match_id: Match ID.
        home_team_id: Home team ID.
        away_team_id: Away team ID.
        is_cup: Whether this is a cup/group-stage tournament.

    Returns:
        Dict with tournament incentive fields for snapshot assembly.
    """
    # Try to get motivation data first (needed for context)
    motivations = []
    try:
        motivations = get_motivation_for_match(conn, match_id)
    except Exception as e:
        print(f"[tournament] motivation read error: {e}")

    # Map motivations by team_id
    mot_map = {m["team_id"]: m for m in motivations}

    snapshot_time = __import__("datetime").datetime.now().isoformat(timespec="seconds")

    home_avoid = None
    away_avoid = None
    home_tanking = None
    away_tanking = None

    # Home team
    if home_team_id and home_team_id in mot_map:
        try:
            ctx = _build_context_from_motivation(mot_map.get(home_team_id), is_cup)
            home_avoid = round(compute_avoid_strong_opponent_score(ctx), 4)
            home_tanking = round(compute_tanking_risk(ctx), 4)

            store_tournament_incentive_snapshot(
                conn,
                {
                    "match_id": match_id,
                    "team_id": home_team_id,
                    "snapshot_time": snapshot_time,
                    "avoid_strong_opponent_score": home_avoid,
                    "tanking_risk_score": home_tanking,
                    "qualification_status": (
                        "qualified"
                        if ctx.get("already_qualified")
                        else "eliminated"
                        if home_tanking and home_tanking > 70
                        else "contending"
                    ),
                    "incentive_summary": "",
                    "raw_json": ctx,
                },
            )
        except Exception as e:
            print(f"[tournament] error home team {home_team_id}: {e}")

    # Away team
    if away_team_id and away_team_id in mot_map:
        try:
            ctx = _build_context_from_motivation(mot_map.get(away_team_id), is_cup)
            away_avoid = round(compute_avoid_strong_opponent_score(ctx), 4)
            away_tanking = round(compute_tanking_risk(ctx), 4)

            store_tournament_incentive_snapshot(
                conn,
                {
                    "match_id": match_id,
                    "team_id": away_team_id,
                    "snapshot_time": snapshot_time,
                    "avoid_strong_opponent_score": away_avoid,
                    "tanking_risk_score": away_tanking,
                    "qualification_status": (
                        "qualified"
                        if ctx.get("already_qualified")
                        else "eliminated"
                        if away_tanking and away_tanking > 70
                        else "contending"
                    ),
                    "incentive_summary": "",
                    "raw_json": ctx,
                },
            )
        except Exception as e:
            print(f"[tournament] error away team {away_team_id}: {e}")

    # Aggregate tournament incentive risk: the higher of the two teams' tanking risks
    agg_risk = None
    if home_tanking is not None and away_tanking is not None:
        agg_risk = round(max(home_tanking, away_tanking), 4)
    elif home_tanking is not None:
        agg_risk = home_tanking
    elif away_tanking is not None:
        agg_risk = away_tanking

    has_data = home_avoid is not None or away_avoid is not None

    return {
        "home_avoid_strong_opponent_score": home_avoid,
        "away_avoid_strong_opponent_score": away_avoid,
        "home_tanking_risk_score": home_tanking,
        "away_tanking_risk_score": away_tanking,
        "tournament_incentive_risk_score": agg_risk,
        "has_tournament_incentive_data": has_data,
    }
