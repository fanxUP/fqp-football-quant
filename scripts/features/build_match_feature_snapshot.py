"""汇总多维数据为 match_feature_snapshots 的可开发骨架。
实际工程中应从数据库读取各类最新快照，并以事务方式写入最终快照。
"""

from __future__ import annotations

from typing import Any


def compute_data_completeness(parts: dict[str, bool]) -> float:
    weights = {
        "official_match": 0.15,
        "official_odds": 0.15,
        "team_mapping": 0.10,
        "team_profile": 0.10,
        "player_value": 0.10,
        "injury": 0.10,
        "lineup": 0.10,
        "stadium_weather": 0.10,
        "motivation_tournament": 0.10,
    }
    return sum((1.0 if parts.get(k) else 0.0) * v * 100 for k, v in weights.items())


def compute_uncertainty(snapshot: dict[str, Any]) -> float:
    score = 0.0
    if not snapshot.get("home_lineup_confirmed") or not snapshot.get("away_lineup_confirmed"):
        score += 12
    if snapshot.get("data_completeness_score", 100) < 80:
        score += 15
    if snapshot.get("tournament_incentive_risk_score", 0) > 65:
        score += 10
    if snapshot.get("weather_impact_score", 0) > 70:
        score += 8
    if abs(float(snapshot.get("rotation_risk_diff") or 0)) > 40:
        score += 8
    return min(100.0, score)


def build_match_feature_snapshot(inputs: dict[str, Any]) -> dict[str, Any]:
    # inputs 代表已经从各业务表读取并规整后的字段集合。
    snapshot = dict(inputs)
    snapshot["data_completeness_score"] = compute_data_completeness(
        inputs.get("completeness_parts", {})
    )
    snapshot["uncertainty_score"] = compute_uncertainty(snapshot)
    return snapshot
