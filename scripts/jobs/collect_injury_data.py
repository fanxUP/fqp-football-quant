"""当日比赛级伤停采集任务。

使用 API-Football fixture injury 接口，不再把免费套餐可查的
2024 历史赛季伤停误用于当前比赛。查询成功但无伤停时，
仍写入比赛级观测回执，以区分“零伤停”和“未获取”。
"""

from __future__ import annotations

import os
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.feature_storage import (
    get_injury_observation_for_match,
    get_player_by_code,
    store_player,
    store_player_availability_snapshot,
    store_team_squad_snapshot,
)
from scripts.features.api_football_fixture_matcher import (
    find_matching_fixture,
    load_api_aliases,
    load_supported_matches,
)


def _business_now() -> datetime:
    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)


def _now() -> str:
    return _business_now().isoformat(timespec="seconds")


POSITION_IMPORTANCE = {
    "GK": 0.95,
    "Goalkeeper": 0.95,
    "CB": 0.85,
    "Defender": 0.75,
    "DM": 0.82,
    "CM": 0.70,
    "AM": 0.76,
    "ST": 0.82,
    "Attacker": 0.78,
    "FB": 0.62,
    "W": 0.58,
    "SUB": 0.30,
}


def _position_importance(api_position: str) -> float:
    for key, value in POSITION_IMPORTANCE.items():
        if key.lower() in (api_position or "").lower():
            return value
    return 0.50


def _extract_injury_fields(injury: dict[str, Any]) -> tuple[str, str, str]:
    """兼容当前 fixture 响应和旧 league 响应的伤停字段。"""
    raw_player = injury.get("player")
    raw_legacy = injury.get("injury")
    player: dict[str, Any] = raw_player if isinstance(raw_player, dict) else {}
    legacy: dict[str, Any] = raw_legacy if isinstance(raw_legacy, dict) else {}
    injury_type = str(player.get("type") or legacy.get("type") or "")
    reason = str(player.get("reason") or legacy.get("reason") or "")
    combined = f"{injury_type} {reason}".lower()
    status = "suspended" if "suspend" in combined else "injured"
    return status, injury_type, reason


def _safe_height(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(" cm", "").strip())
    except ValueError:
        return None


def _get_or_create_player(conn: Any, player_data: dict[str, Any]) -> int | None:
    player_code = f"apifootball:{player_data.get('id')}"
    existing = get_player_by_code(conn, player_code)
    if existing:
        return int(existing["id"])
    return store_player(
        conn,
        {
            "player_code": player_code,
            "player_name_en": player_data.get("name", ""),
            "player_name_cn": "",
            "birth_date": (
                player_data.get("birth", {}).get("date")
                if isinstance(player_data.get("birth"), dict)
                else None
            ),
            "nationality": player_data.get("nationality", ""),
            "primary_position": player_data.get("position", ""),
            "secondary_positions": [],
            "preferred_foot": "",
            "height_cm": _safe_height(player_data.get("height")),
        },
    )


def _store_team_observations(
    conn: Any,
    match: dict[str, Any],
    api_fixture_id: int,
    injuries: list[dict[str, Any]],
    alias_to_team_id: dict[str, int],
    snapshot_time: str,
) -> int:
    counts: dict[int, Counter[str]] = {
        match["home_team_id"]: Counter(),
        match["away_team_id"]: Counter(),
    }
    for injury in injuries:
        api_team_name = str(injury.get("team", {}).get("name") or "")
        team_id = alias_to_team_id.get(api_team_name)
        if team_id not in counts:
            continue
        status, _, _ = _extract_injury_fields(injury)
        counts[team_id][status] += 1

    stored = 0
    for team_id, status_counts in counts.items():
        store_team_squad_snapshot(
            conn,
            {
                "team_id": team_id,
                "competition_season_id": match["competition_season_id"],
                "snapshot_time": snapshot_time,
                "injured_players_count": status_counts["injured"],
                "suspended_players_count": status_counts["suspended"],
                "doubtful_players_count": status_counts["doubtful"],
                "key_absence_count": 0,
                "squad_health_score": max(
                    0.0,
                    100.0 - status_counts["injured"] * 8.0 - status_counts["suspended"] * 10.0,
                ),
                "data_confidence": 0.90,
                "raw_json": {
                    "observation_type": "fixture_injuries",
                    "official_match_id": match["id"],
                    "api_fixture_id": api_fixture_id,
                    "source_result_count": len(injuries),
                },
            },
        )
        stored += 1
    return stored


def _run_impl(
    dry_run: bool = False,
    business_date: date | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}

    target_date = business_date or _business_now().date()
    start_time = datetime.combine(target_date, time.min)
    end_time = start_time + timedelta(days=1)
    client = ApiFootballClient(api_key=api_key)
    matches_matched = 0
    matches_unmatched = 0
    matches_already_observed = 0
    observations_stored = 0
    injuries_collected = 0
    provider_errors: list[dict[str, Any]] = []
    processing_errors: list[str] = []

    try:
        with get_db() as conn:
            matches = load_supported_matches(
                conn,
                start_time=start_time,
                end_time=end_time,
            )
            if not matches:
                return {
                    "status": "ok",
                    "quality_status": "not_due",
                    "note": "no supported selling matches for target date",
                    "target_date": target_date.isoformat(),
                    "api_calls_used": 0,
                }

            alias_to_team_id = load_api_aliases(conn)
            fixtures = client.get_fixtures(date=target_date.isoformat())
            fixture_errors = client.last_response_meta.get("errors") or {}
            if fixture_errors:
                provider_errors.append({"endpoint": "fixtures", "errors": fixture_errors})

            snapshot_time = _now()
            for match in matches:
                if get_injury_observation_for_match(
                    conn, match["id"], match["home_team_id"]
                ) and get_injury_observation_for_match(conn, match["id"], match["away_team_id"]):
                    matches_already_observed += 1
                    continue
                fixture = find_matching_fixture(match, fixtures, alias_to_team_id)
                if fixture is None:
                    matches_unmatched += 1
                    continue
                matches_matched += 1
                fixture_id = int(fixture.get("fixture", {}).get("id") or 0)
                if not fixture_id:
                    matches_unmatched += 1
                    matches_matched -= 1
                    continue
                try:
                    injuries = client.get_injuries(fixture=fixture_id)
                    injury_errors = client.last_response_meta.get("errors") or {}
                    if injury_errors:
                        provider_errors.append(
                            {
                                "endpoint": "injuries",
                                "official_match_id": match["id"],
                                "api_fixture_id": fixture_id,
                                "errors": injury_errors,
                            }
                        )
                        continue
                    if dry_run:
                        continue

                    observations_stored += _store_team_observations(
                        conn,
                        match,
                        fixture_id,
                        injuries,
                        alias_to_team_id,
                        snapshot_time,
                    )
                    for injury in injuries:
                        raw_player = injury.get("player")
                        player_data: dict[str, Any] = (
                            raw_player if isinstance(raw_player, dict) else {}
                        )
                        api_team_name = str(injury.get("team", {}).get("name") or "")
                        team_id = alias_to_team_id.get(api_team_name)
                        if team_id not in {
                            match["home_team_id"],
                            match["away_team_id"],
                        }:
                            continue
                        player_id = _get_or_create_player(conn, player_data)
                        if not player_id:
                            continue
                        status, injury_type, reason = _extract_injury_fields(injury)
                        position_importance = _position_importance(
                            str(player_data.get("position") or "")
                        )
                        store_player_availability_snapshot(
                            conn,
                            {
                                "player_id": player_id,
                                "team_id": team_id,
                                "competition_season_id": match["competition_season_id"],
                                "snapshot_time": snapshot_time,
                                "availability_status": status,
                                "injury_type": injury_type,
                                "injury_body_part": reason,
                                "is_suspended": status == "suspended",
                                "suspension_reason": reason if status == "suspended" else "",
                                "source_name": "api-football",
                                "source_confidence": 0.90,
                                "recent_minutes_share": 0.0,
                                "team_market_value_share": 0.0,
                                "position_importance_score": position_importance,
                                "replacement_quality_score": 0.5,
                                "absence_impact_score": position_importance * 85.0,
                                "raw_json": {
                                    **injury,
                                    "official_match_id": match["id"],
                                    "api_fixture_id": fixture_id,
                                },
                            },
                        )
                        injuries_collected += 1
                except Exception as exc:
                    processing_errors.append(f"match {match['id']}: {exc}")

    finally:
        client.close()

    quality_status = (
        "degraded" if provider_errors or processing_errors or matches_unmatched else "healthy"
    )
    return {
        "status": "dry_run" if dry_run else "ok",
        "quality_status": quality_status,
        "target_date": target_date.isoformat(),
        "matches_supported": (matches_matched + matches_unmatched + matches_already_observed),
        "matches_matched": matches_matched,
        "matches_unmatched": matches_unmatched,
        "matches_already_observed": matches_already_observed,
        "observations_stored": observations_stored,
        "injuries_collected": injuries_collected,
        "provider_errors": provider_errors,
        "processing_errors": processing_errors,
        "api_calls_used": client.call_count_today,
    }


def run(
    dry_run: bool = False,
    business_date: date | None = None,
    season: int | None = None,
) -> dict[str, Any]:
    """采集当日比赛伤停；season 仅保留旧调用兼容，不再查历史赛季。"""
    run_id = start_tracked_job(
        "injury_collection",
        "feature_agent",
        {
            "dry_run": dry_run,
            "business_date": business_date.isoformat() if business_date else None,
            "ignored_legacy_season": season,
        },
    )
    try:
        result = _run_impl(dry_run=dry_run, business_date=business_date)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    print(run(dry_run=dry))
