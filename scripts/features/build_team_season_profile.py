"""构建球队赛季画像。
输入：球员赛季画像、球队基础表、赛事赛季。
输出：team_season_profiles 快照。
注意：这里是可开发骨架，不包含外部数据抓取逻辑。
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from statistics import median
from typing import Any


def safe_log_value(value: float | None) -> float:
    return math.log((value or 0) + 1.0)


def build_market_value_summary(players: Iterable[dict[str, Any]]) -> dict[str, float]:
    vals = sorted([float(p.get("market_value") or 0) for p in players], reverse=True)
    if not vals:
        return {
            "total_market_value": 0.0,
            "avg_market_value": 0.0,
            "median_market_value": 0.0,
            "top_5_market_value": 0.0,
            "top_11_market_value": 0.0,
            "squad_depth_value": 0.0,
        }
    return {
        "total_market_value": sum(vals),
        "avg_market_value": sum(vals) / len(vals),
        "median_market_value": float(median(vals)),
        "top_5_market_value": sum(vals[:5]),
        "top_11_market_value": sum(vals[:11]),
        "squad_depth_value": sum(vals[11:]),
    }


def compute_squad_depth_score(players: Iterable[dict[str, Any]]) -> float:
    players = list(players)
    if not players:
        return 0.0
    bench = sorted(players, key=lambda p: float(p.get("market_value") or 0), reverse=True)[11:]
    bench_value = sum(float(p.get("market_value") or 0) for p in bench)
    recent_minutes = sum(float(p.get("recent_5_minutes") or 0) for p in bench)
    raw = safe_log_value(bench_value) * 8 + min(recent_minutes / 90.0, 20)
    return max(0.0, min(100.0, raw))


def build_team_season_profile(
    team_id: int, competition_season_id: int, players: list[dict[str, Any]]
) -> dict[str, Any]:
    value_summary = build_market_value_summary(players)
    return {
        "team_id": team_id,
        "competition_season_id": competition_season_id,
        "squad_size": len(players),
        **value_summary,
        "squad_depth_score": compute_squad_depth_score(players),
    }
