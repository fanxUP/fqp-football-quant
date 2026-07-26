"""临场首发阵容采集任务。

仅查询开赛前短窗口内的比赛，每 30 分钟运行时仍可控制
API-Football 免费额度。API fixture 返回的 lineup 是临场已确认阵容。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.feature_storage import (
    get_player_by_code,
    store_match_lineup_player,
    store_match_lineup_snapshot,
    store_player,
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
            "primary_position": player_data.get("pos") or player_data.get("position", ""),
            "secondary_positions": [],
            "preferred_foot": "",
            "height_cm": _safe_height(player_data.get("height")),
        },
    )


def _process_lineup(
    conn: Any,
    match_id: int,
    team_data: dict[str, Any],
    team_id: int,
    snapshot_time: str,
) -> int | None:
    """保存 API 已公布的首发和替补名单。"""
    formation = str(team_data.get("formation") or "")
    start_xi = team_data.get("startXI") or []
    substitutes = team_data.get("substitutes") or []
    player_records: list[dict[str, Any]] = []
    key_count = 0

    for entry in start_xi:
        player_info = entry.get("player") or {}
        player_id = _get_or_create_player(conn, player_info)
        if not player_id:
            continue
        position = str(player_info.get("pos") or player_info.get("position") or "")
        player_records.append(
            {
                "player_id": player_id,
                "is_starting": True,
                "is_substitute": False,
                "position": position,
                "tactical_role": "",
                "market_value": None,
                "recent_minutes": None,
                "key_player_score": 50.0 if position in ("G", "D", "M", "F") else 30.0,
            }
        )
        if position in ("G", "D"):
            key_count += 1

    for entry in substitutes:
        player_info = entry.get("player") or {}
        player_id = _get_or_create_player(conn, player_info)
        if not player_id:
            continue
        player_records.append(
            {
                "player_id": player_id,
                "is_starting": False,
                "is_substitute": True,
                "position": str(player_info.get("pos") or player_info.get("position") or ""),
                "tactical_role": "",
                "market_value": None,
                "recent_minutes": None,
                "key_player_score": 20.0,
            }
        )

    lineup_id = store_match_lineup_snapshot(
        conn,
        {
            "match_id": match_id,
            "team_id": team_id,
            "snapshot_time": snapshot_time,
            "lineup_type": "confirmed",
            "source_name": "api-football",
            "source_confidence": 0.95,
            "formation": formation,
            "formation_changed": False,
            "goalkeeper_changed": False,
            "center_back_pair_changed": False,
            "starting_11_market_value": None,
            "starting_11_avg_age": None,
            "starting_11_recent_minutes": None,
            "starting_11_key_player_count": key_count,
            "bench_market_value": None,
            "bench_strength_score": 50.0,
            "lineup_strength_score": 50.0,
            "rotation_risk_score": 5.0,
            "lineup_uncertainty_score": 5.0,
            "raw_json": team_data,
        },
    )
    if not lineup_id:
        return None
    for player_record in player_records:
        player_record["lineup_snapshot_id"] = lineup_id
        store_match_lineup_player(conn, player_record)
    return lineup_id


def _has_complete_confirmed_lineup(conn: Any, match_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(DISTINCT team_id)
            FROM match_lineup_snapshots
            WHERE match_id = %s AND lineup_type = 'confirmed'
            """,
            (match_id,),
        )
        row = cur.fetchone()
    return bool(row and int(row[0]) >= 2)


def _run_impl(
    dry_run: bool = False,
    *,
    window_minutes: int | None = None,
) -> dict[str, Any]:
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}

    lookahead = window_minutes or int(os.getenv("LINEUP_LOOKAHEAD_MINUTES", "90"))
    now = _business_now()
    cutoff = now + timedelta(minutes=lookahead)
    client = ApiFootballClient(api_key=api_key)
    matches_matched = 0
    matches_unmatched = 0
    matches_waiting = 0
    matches_already_complete = 0
    lineups_collected = 0
    provider_errors: list[dict[str, Any]] = []
    processing_errors: list[str] = []

    try:
        with get_db() as conn:
            matches = load_supported_matches(conn, start_time=now, end_time=cutoff)
            if not matches:
                return {
                    "status": "ok",
                    "quality_status": "not_due",
                    "note": "no supported matches in pre-match window",
                    "window_minutes": lookahead,
                    "api_calls_used": 0,
                }

            alias_to_team_id = load_api_aliases(conn)
            match_dates: dict[str, list[dict[str, Any]]] = {}
            for match in matches:
                match_dates.setdefault(match["kickoff_time"].date().isoformat(), []).append(match)

            snapshot_time = _now()
            for match_date, day_matches in match_dates.items():
                fixtures = client.get_fixtures(date=match_date)
                fixture_errors = client.last_response_meta.get("errors") or {}
                if fixture_errors:
                    provider_errors.append(
                        {"endpoint": "fixtures", "date": match_date, "errors": fixture_errors}
                    )
                    continue

                for match in day_matches:
                    if _has_complete_confirmed_lineup(conn, match["id"]):
                        matches_already_complete += 1
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
                        detail_rows = client.get_fixtures(fixture_id=fixture_id)
                        detail_errors = client.last_response_meta.get("errors") or {}
                        if detail_errors:
                            provider_errors.append(
                                {
                                    "endpoint": "fixture_detail",
                                    "official_match_id": match["id"],
                                    "api_fixture_id": fixture_id,
                                    "errors": detail_errors,
                                }
                            )
                            continue
                        lineups = detail_rows[0].get("lineups", []) if detail_rows else []
                        if not lineups:
                            matches_waiting += 1
                            continue
                        if dry_run:
                            continue
                        for team_lineup in lineups:
                            api_team_name = str(team_lineup.get("team", {}).get("name") or "")
                            team_id = alias_to_team_id.get(api_team_name)
                            if team_id is None or team_id not in {
                                match["home_team_id"],
                                match["away_team_id"],
                            }:
                                continue
                            if _process_lineup(
                                conn,
                                match["id"],
                                team_lineup,
                                team_id,
                                snapshot_time,
                            ):
                                lineups_collected += 1
                    except Exception as exc:
                        processing_errors.append(f"match {match['id']}: {exc}")
    finally:
        client.close()

    if provider_errors or processing_errors or matches_unmatched:
        quality_status = "degraded"
    elif matches_waiting and not lineups_collected:
        quality_status = "waiting"
    else:
        quality_status = "healthy"
    return {
        "status": "dry_run" if dry_run else "ok",
        "quality_status": quality_status,
        "window_minutes": lookahead,
        "matches_supported": (matches_matched + matches_unmatched + matches_already_complete),
        "matches_matched": matches_matched,
        "matches_unmatched": matches_unmatched,
        "matches_waiting_lineup": matches_waiting,
        "matches_already_complete": matches_already_complete,
        "lineups_collected": lineups_collected,
        "provider_errors": provider_errors,
        "processing_errors": processing_errors,
        "api_calls_used": client.call_count_today,
    }


def run(
    dry_run: bool = False,
    *,
    window_minutes: int | None = None,
) -> dict[str, Any]:
    run_id = start_tracked_job(
        "lineup_collection",
        "feature_agent",
        {"dry_run": dry_run, "window_minutes": window_minutes},
    )
    try:
        result = _run_impl(dry_run=dry_run, window_minutes=window_minutes)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    print(run(dry_run=dry))
