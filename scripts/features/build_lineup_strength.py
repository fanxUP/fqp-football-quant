"""首发阵容强度特征构建器。

从 match_lineup_snapshots 读取阵容数据，结合 lineup_strength_weights.yaml
计算首发强度、轮换风险等指标。

输出字段（写入 match_feature_snapshots）:
  - home_lineup_confirmed / away_lineup_confirmed
  - home_starting_11_value / away_starting_11_value / starting_11_value_diff
  - home_lineup_strength_score / away_lineup_strength_score / lineup_strength_diff
  - home_rotation_risk_score / away_rotation_risk_score / rotation_risk_diff
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from scripts.feature_storage import get_lineup_for_match

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "configs" / "lineup_strength_weights.yaml"
)

_weights: dict[str, Any] | None = None


def _load_weights() -> dict[str, Any]:
    global _weights
    if _weights is None:
        with open(_CONFIG_PATH) as f:
            _weights = yaml.safe_load(f)
    return _weights


WEIGHTS: dict[str, float] = {
    "starting_11_market_value_score": 0.25,
    "recent_minutes_stability": 0.20,
    "key_player_integrity": 0.20,
    "positional_completeness": 0.15,
    "formation_stability": 0.10,
    "bench_strength": 0.10,
}


def value_score(total_value: float, league_reference_value: float) -> float:
    """Log-scale market value → 0-100 score."""
    if league_reference_value <= 0:
        return 50.0
    ratio = math.log(total_value + 1) / math.log(league_reference_value + 1)
    return max(0.0, min(100.0, ratio * 70))


def compute_lineup_strength(
    lineup: dict[str, Any], league_reference_value: float = 100_000_000
) -> float:
    """6-factor weighted lineup strength score (preserves original skeleton signature)."""
    components = {
        "starting_11_market_value_score": value_score(
            float(lineup.get("starting_11_market_value") or 0), league_reference_value
        ),
        "recent_minutes_stability": float(lineup.get("recent_minutes_stability") or 50),
        "key_player_integrity": float(lineup.get("key_player_integrity") or 50),
        "positional_completeness": float(lineup.get("positional_completeness") or 50),
        "formation_stability": float(lineup.get("formation_stability") or 50),
        "bench_strength": float(lineup.get("bench_strength_score") or 50),
    }
    return sum(components[k] * WEIGHTS[k] for k in WEIGHTS)


def compute_rotation_risk(lineup: dict[str, Any]) -> float:
    """Compute rotation risk from lineup changes.

    Higher score = more rotation = more uncertainty.
    Factors: formation change, GK change, CB pair change, lineup uncertainty.
    """
    risk = 0.0
    if lineup.get("formation_changed"):
        risk += 25
    if lineup.get("goalkeeper_changed"):
        risk += 20
    if lineup.get("center_back_pair_changed"):
        risk += 30
    risk += float(lineup.get("lineup_uncertainty_score") or 0) * 0.25
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
                home_strength = round(compute_lineup_strength(home_lineup), 4)
                home_value = home_lineup.get("starting_11_market_value")
                home_rotation = round(compute_rotation_risk(home_lineup), 4)
        except Exception as e:
            print(f"[lineup] error home team {home_team_id}: {e}")

    if away_team_id:
        try:
            away_lineup = get_lineup_for_match(conn, match_id, away_team_id)
            if away_lineup:
                away_strength = round(compute_lineup_strength(away_lineup), 4)
                away_value = away_lineup.get("starting_11_market_value")
                away_rotation = round(compute_rotation_risk(away_lineup), 4)
        except Exception as e:
            print(f"[lineup] error away team {away_team_id}: {e}")

    has_lineup = home_lineup is not None or away_lineup is not None

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
        "has_lineup_data": has_lineup,
    }
