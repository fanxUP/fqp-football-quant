"""伤停影响特征构建器。

从 player_availability_snapshots 读取伤停数据，结合 injury_impact_weights.yaml
配置文件计算缺阵影响评分。

输出字段（写入 match_feature_snapshots）:
  - home_absence_impact_score / away_absence_impact_score
  - absence_impact_diff
  - home_key_absence_count / away_key_absence_count
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from scripts.feature_storage import get_injuries_for_team

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


def _status_to_weight(status: str) -> float:
    config = _load_weights()
    status_map = config.get("availability_status", {})
    return float(status_map.get(status, 0.3))


def compute_absence_impact(player_status: dict[str, Any]) -> float:
    """Compute absence impact for a single player. (Preserves original skeleton signature.)"""
    if player_status.get("availability_status") == "available":
        return 0.0
    weights = _load_weights().get("absence_impact_weights", {})
    score = 0.0
    score += (
        float(player_status.get("recent_minutes_share") or 0)
        * 100
        * float(weights.get("recent_minutes_share", 0.30))
    )
    score += (
        float(player_status.get("team_market_value_share") or 0)
        * 100
        * float(weights.get("team_market_value_share", 0.25))
    )
    score += (
        float(player_status.get("position_importance_score") or 0.5)
        * 100
        * float(weights.get("position_importance_score", 0.20))
    )
    score += float(player_status.get("key_player_score") or 0) * float(
        weights.get("key_player_score", 0.15)
    )
    score += (
        float(player_status.get("replacement_difficulty") or 0.5)
        * 100
        * float(weights.get("replacement_difficulty", 0.10))
    )
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
        if status_w == 0:
            continue

        if inj.get("absence_impact_score") is not None:
            impact = float(inj["absence_impact_score"]) * status_w
        else:
            impact = compute_absence_impact(inj) * status_w

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
    home_impact = 0.0
    away_impact = 0.0
    home_key = 0
    away_key = 0
    home_injuries: list[dict] = []
    away_injuries: list[dict] = []

    if home_team_id:
        try:
            home_injuries = get_injuries_for_team(conn, home_team_id)
            result = compute_team_absence_impact(home_injuries)
            home_impact = result["total_impact_score"]
            home_key = result["key_absence_count"]
        except Exception as e:
            print(f"[injury] error home team {home_team_id}: {e}")

    if away_team_id:
        try:
            away_injuries = get_injuries_for_team(conn, away_team_id)
            result = compute_team_absence_impact(away_injuries)
            away_impact = result["total_impact_score"]
            away_key = result["key_absence_count"]
        except Exception as e:
            print(f"[injury] error away team {away_team_id}: {e}")

    covered_team_count = int(bool(home_injuries)) + int(bool(away_injuries))
    return {
        "home_absence_impact_score": home_impact if home_injuries else None,
        "away_absence_impact_score": away_impact if away_injuries else None,
        "absence_impact_diff": (
            round(home_impact - away_impact, 4)
            if home_injuries and away_injuries
            else None
        ),
        "home_key_absence_count": home_key if home_injuries else None,
        "away_key_absence_count": away_key if away_injuries else None,
        "has_injury_data": covered_team_count == 2,
        "covered_team_count": covered_team_count,
    }
