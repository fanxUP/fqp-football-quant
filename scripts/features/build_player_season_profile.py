"""球员赛季画像清洗与评分骨架。"""

from __future__ import annotations

from typing import Any


def compute_key_player_score(row: dict[str, Any]) -> float:
    minutes_share = float(row.get("minutes_share") or 0)
    starter_rate = float(row.get("starter_rate") or 0)
    market_value_share = float(row.get("team_market_value_share") or 0)
    position_importance = float(row.get("position_importance_score") or 0.5)
    contribution = float(
        row.get("goal_contribution_score") or row.get("defensive_contribution_score") or 0
    )
    score = (
        minutes_share * 30
        + starter_rate * 20
        + market_value_share * 20
        + position_importance * 15
        + contribution * 15
    )
    return max(0.0, min(100.0, score))


def normalize_player_profile(raw: dict[str, Any]) -> dict[str, Any]:
    profile = dict(raw)
    profile["key_player_score"] = compute_key_player_score(profile)
    profile["is_key_player"] = profile["key_player_score"] >= 65
    return profile
