"""首发阵容强度特征构建器。

从 match_lineup_snapshots 读取阵容数据，使用本模块 WEIGHTS 常量
计算首发强度、轮换风险等指标。

输出字段（写入 match_feature_snapshots）:
  - home_lineup_confirmed / away_lineup_confirmed
  - home_starting_11_value / away_starting_11_value / starting_11_value_diff
  - home_lineup_strength_score / away_lineup_strength_score / lineup_strength_diff
  - home_rotation_risk_score / away_rotation_risk_score / rotation_risk_diff
"""

from __future__ import annotations

import math
from typing import Any

from scripts.feature_schema import numeric_feature_value
from scripts.feature_storage import get_lineup_for_match

WEIGHTS: dict[str, float] = {
    "starting_11_market_value_score": 0.25,
    "recent_minutes_stability": 0.20,
    "key_player_integrity": 0.20,
    "positional_completeness": 0.15,
    "formation_stability": 0.10,
    "bench_strength": 0.10,
}


def value_score(total_value: float | None, league_reference_value: float | None) -> float | None:
    """Log-scale market value → 0-100 score."""
    total = numeric_feature_value(total_value)
    reference = numeric_feature_value(league_reference_value)
    if not math.isfinite(total) or total < 0 or not math.isfinite(reference) or reference <= 0:
        return None
    ratio = math.log1p(total) / math.log1p(reference)
    return max(0.0, min(100.0, ratio * 70))


def compute_lineup_strength(
    lineup: dict[str, Any], league_reference_value: float | None = None
) -> float | None:
    """Compute the existing heuristic only with all six known components."""
    market_score = value_score(lineup.get("starting_11_market_value"), league_reference_value)
    if market_score is None:
        return None
    components = {
        "starting_11_market_value_score": market_score,
        "recent_minutes_stability": numeric_feature_value(lineup.get("recent_minutes_stability")),
        "key_player_integrity": numeric_feature_value(lineup.get("key_player_integrity")),
        "positional_completeness": numeric_feature_value(lineup.get("positional_completeness")),
        "formation_stability": numeric_feature_value(lineup.get("formation_stability")),
        "bench_strength": numeric_feature_value(lineup.get("bench_strength_score")),
    }
    if any(not math.isfinite(value) or not 0 <= value <= 100 for value in components.values()):
        return None
    return sum(components[k] * WEIGHTS[k] for k in WEIGHTS)


def compute_rotation_risk(lineup: dict[str, Any]) -> float | None:
    """Compute rotation risk from lineup changes.

    Higher score = more rotation = more uncertainty.
    Factors: formation change, GK change, CB pair change, lineup uncertainty.
    """
    changes = ("formation_changed", "goalkeeper_changed", "center_back_pair_changed")
    uncertainty = numeric_feature_value(lineup.get("lineup_uncertainty_score"))
    if (
        any(type(lineup.get(field)) is not bool for field in changes)
        or not math.isfinite(uncertainty)
        or not 0 <= uncertainty <= 100
    ):
        return None
    risk = 0.0
    if lineup.get("formation_changed"):
        risk += 25
    if lineup.get("goalkeeper_changed"):
        risk += 20
    if lineup.get("center_back_pair_changed"):
        risk += 30
    risk += uncertainty * 0.25
    return max(0.0, min(100.0, risk))


def build_lineup_features(
    conn: Any,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
) -> dict[str, Any]:
    """Build lineup features for a match.

    Returns dict with fields for match_feature_snapshots assembly.
    """
    home_lineup = None
    away_lineup = None
    home_strength = None
    away_strength = None
    home_value = None
    away_value = None
    home_rotation = None
    away_rotation = None

    if home_team_id:
        try:
            home_lineup = get_lineup_for_match(conn, match_id, home_team_id)
            if home_lineup:
                strength = compute_lineup_strength(home_lineup)
                home_strength = round(strength, 4) if strength is not None else None
                home_value = home_lineup.get("starting_11_market_value")
                rotation = compute_rotation_risk(home_lineup)
                home_rotation = round(rotation, 4) if rotation is not None else None
        except Exception as e:
            print(f"[lineup] error home team {home_team_id}: {e}")

    if away_team_id:
        try:
            away_lineup = get_lineup_for_match(conn, match_id, away_team_id)
            if away_lineup:
                strength = compute_lineup_strength(away_lineup)
                away_strength = round(strength, 4) if strength is not None else None
                away_value = away_lineup.get("starting_11_market_value")
                rotation = compute_rotation_risk(away_lineup)
                away_rotation = round(rotation, 4) if rotation is not None else None
        except Exception as e:
            print(f"[lineup] error away team {away_team_id}: {e}")

    covered_team_count = int(home_lineup is not None) + int(away_lineup is not None)

    return {
        "home_lineup_confirmed": (
            home_lineup.get("lineup_type") == "confirmed" if home_lineup else False
        ),
        "away_lineup_confirmed": (
            away_lineup.get("lineup_type") == "confirmed" if away_lineup else False
        ),
        "home_starting_11_value": home_value,
        "away_starting_11_value": away_value,
        "starting_11_value_diff": (
            round((home_value or 0) - (away_value or 0), 2)
            if home_value is not None and away_value is not None
            else None
        ),
        "home_lineup_strength_score": home_strength,
        "away_lineup_strength_score": away_strength,
        "lineup_strength_diff": (
            round((home_strength or 0) - (away_strength or 0), 4)
            if home_strength is not None and away_strength is not None
            else None
        ),
        "home_rotation_risk_score": home_rotation,
        "away_rotation_risk_score": away_rotation,
        "rotation_risk_diff": (
            round((home_rotation or 0) - (away_rotation or 0), 4)
            if home_rotation is not None and away_rotation is not None
            else None
        ),
        "has_lineup_data": covered_team_count == 2,
        "covered_team_count": covered_team_count,
    }
