"""伤停影响特征构建器。

从 player_availability_snapshots 读取伤停数据，结合 injury_impact_weights.yaml
配置文件计算缺阵影响评分。

输出字段（写入 match_feature_snapshots）:
  - home_absence_impact_score / away_absence_impact_score
  - absence_impact_diff
  - home_key_absence_count / away_key_absence_count
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from scripts.feature_schema import numeric_feature_value
from scripts.feature_storage import (
    get_injuries_for_match,
    get_injury_observation_for_match,
)

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent / "configs" / "injury_impact_weights.yaml"
)

_weights: dict[str, Any] | None = None


def _load_weights() -> dict[str, Any]:
    global _weights
    if _weights is None:
        with open(_CONFIG_PATH) as f:
            _weights = yaml.safe_load(f)
    return _weights


def _status_to_weight(status: str) -> float | None:
    config = _load_weights()
    status_map = config.get("availability_status", {})
    if status == "unknown" or status not in status_map:
        return None
    value = numeric_feature_value(status_map[status])
    return value if math.isfinite(value) and 0 <= value <= 1 else None


def compute_absence_impact(player_status: dict[str, Any]) -> float | None:
    """Retain the existing heuristic only when its inputs are all known."""
    if player_status.get("availability_status") == "available":
        return 0.0
    if _status_to_weight(player_status.get("availability_status", "unknown")) is None:
        return None
    weights = _load_weights().get("absence_impact_weights", {})
    score = 0.0
    for field, default_weight in (
        ("recent_minutes_share", 0.30),
        ("team_market_value_share", 0.25),
        ("position_importance_score", 0.20),
        ("key_player_score", 0.15),
        ("replacement_difficulty", 0.10),
    ):
        value = numeric_feature_value(player_status.get(field))
        upper = 100 if field == "key_player_score" else 1
        if not math.isfinite(value) or not 0 <= value <= upper:
            return None
        score += value / upper * 100 * float(weights.get(field, default_weight))
    if player_status.get("is_suspended"):
        score += 5
    return max(0.0, min(100.0, score))


def compute_team_absence_impact(injuries: list[dict]) -> dict[str, Any]:
    """Aggregate absence impact across a team.

    Args:
        injuries: List of injury dicts from get_injuries_for_team().

    Returns:
        Dict with total_impact, key_absence_count, per-player details.
    """
    total = 0.0
    key_count = 0

    for inj in injuries:
        status = inj.get("availability_status", "unknown")
        status_w = _status_to_weight(status)
        if status_w is None:
            return {"total_impact_score": None, "key_absence_count": None}
        if status_w == 0:
            continue

        # Legacy stored scores were position-based placeholders. Requiring the
        # actual components prevents those rows from becoming new evidence.
        raw_impact = compute_absence_impact(inj)
        if raw_impact is None:
            return {"total_impact_score": None, "key_absence_count": None}
        impact = raw_impact * status_w

        total += impact
        if impact > 30:
            key_count += 1

    return {
        "total_impact_score": round(total, 4),
        "key_absence_count": key_count,
    }


def build_injury_features(
    conn: Any,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
) -> dict[str, Any]:
    """Build injury/absence features for a match.

    Returns dict with fields for match_feature_snapshots assembly.
    """
    home_impact = None
    away_impact = None
    home_key = None
    away_key = None
    home_injuries: list[dict] = []
    away_injuries: list[dict] = []
    home_observation = None
    away_observation = None

    if home_team_id:
        try:
            home_injuries = get_injuries_for_match(conn, match_id, home_team_id)
            home_observation = get_injury_observation_for_match(conn, match_id, home_team_id)
            result = compute_team_absence_impact(home_injuries)
            home_impact = result["total_impact_score"]
            home_key = result["key_absence_count"]
        except Exception as e:
            home_observation = None
            print(f"[injury] error home team {home_team_id}: {e}")

    if away_team_id:
        try:
            away_injuries = get_injuries_for_match(conn, match_id, away_team_id)
            away_observation = get_injury_observation_for_match(conn, match_id, away_team_id)
            result = compute_team_absence_impact(away_injuries)
            away_impact = result["total_impact_score"]
            away_key = result["key_absence_count"]
        except Exception as e:
            away_observation = None
            print(f"[injury] error away team {away_team_id}: {e}")

    covered_team_count = int(home_observation is not None) + int(away_observation is not None)
    return {
        "home_absence_impact_score": home_impact if home_observation is not None else None,
        "away_absence_impact_score": away_impact if away_observation is not None else None,
        "absence_impact_diff": (
            round(home_impact - away_impact, 4)
            if home_observation is not None
            and away_observation is not None
            and home_impact is not None
            and away_impact is not None
            else None
        ),
        "home_key_absence_count": home_key if home_observation is not None else None,
        "away_key_absence_count": away_key if away_observation is not None else None,
        "has_injury_data": covered_team_count == 2,
        "covered_team_count": covered_team_count,
    }
