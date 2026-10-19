"""临场首发阵容采集任务。

仅查询开赛前短窗口内的比赛，每 30 分钟运行时仍可控制
API-Football 免费额度。API fixture 返回的 lineup 是临场已确认阵容。
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.api_football_player import get_or_create_player
from scripts.business_time import business_now_naive as _business_now
from scripts.business_time import business_now_naive_iso as _now
from scripts.data_contracts import FactStatus
from scripts.features.api_football_fixture_matcher import (
    find_matching_fixture,
    load_api_aliases,
    load_supported_matches,
)
from scripts.player_observations import (
    begin_player_group,
    has_fresh_team_checks,
    legacy_snapshot_time,
    record_failed_player_query,
    record_lineup_status,
    store_lineup_observation,
)


def _get_or_create_player(conn: Any, player_data: dict[str, Any]) -> int | None:
    return get_or_create_player(conn, player_data, prefer_short_position=True, commit=False)


def _process_lineup(
    conn: Any,
    match_id: int,
    team_data: dict[str, Any],
    team_id: int,
    snapshot_time: str | datetime,
    *,
    api_fixture_id: int,
    acquired_at: datetime | None = None,
) -> int | None:
    """Commit one team source fact/header/complete roster, or roll it all back."""
    acquired = datetime.now(UTC) if acquired_at is None else acquired_at
    try:
        begin_player_group(conn)
        snapshot_time = legacy_snapshot_time(snapshot_time)
        if (
            not isinstance(team_data, dict)
            or len(json.dumps(team_data, allow_nan=False).encode()) > 65536
        ):
            raise ValueError("lineup response is invalid or exceeds 64KiB")
        starters = team_data.get("startXI")
        bench = team_data.get("substitutes")
        if (
            not isinstance(starters, list)
            or not isinstance(bench, list)
            or len(starters) + len(bench) > 64
        ):
            raise ValueError("lineup requires explicit bounded player arrays")
        if len(starters) != 11:
            record_lineup_status(
                conn,
                match_id=match_id,
                team_id=team_id,
                api_fixture_id=api_fixture_id,
                acquired_at=acquired,
                status=FactStatus.UNKNOWN,
                source_response=team_data,
            )
            conn.commit()
            return None
        formation = str(team_data.get("formation") or "")
        start_xi = team_data.get("startXI") or []
        substitutes = team_data.get("substitutes") or []
        player_records: list[dict[str, Any]] = []
        key_count = 0

        for entry in start_xi:
            player_info = entry.get("player") or {}
            player_id = _get_or_create_player(conn, player_info)
            if not player_id:
                raise ValueError("lineup player identity unresolved")
            position = str(player_info.get("pos") or player_info.get("position") or "")
            player_records.append(
                {
                    "player_id": player_id,
                    "source_player_id": player_info["id"],
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
                raise ValueError("lineup player identity unresolved")
            player_records.append(
                {
                    "player_id": player_id,
                    "source_player_id": player_info["id"],
                    "is_starting": False,
                    "is_substitute": True,
                    "position": str(player_info.get("pos") or player_info.get("position") or ""),
                    "tactical_role": "",
                    "market_value": None,
                    "recent_minutes": None,
                    "key_player_score": 20.0,
                }
            )

        lineup_id = store_lineup_observation(
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
            player_records,
            api_fixture_id=api_fixture_id,
            acquired_at=acquired,
        )
        conn.commit()
        return lineup_id
    except Exception:
        conn.rollback()
        raise


def _has_recent_lineup_checks(conn: Any, match: dict) -> bool:
    return has_fresh_team_checks(
        conn,
        match_id=match["id"],
        team_ids=[match["home_team_id"], match["away_team_id"]],
        domain="lineup",
    )


def _run_impl(dry_run: bool = False, *, window_minutes: int | None = None) -> dict[str, Any]:
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}
    lookahead = window_minutes or int(os.getenv("LINEUP_LOOKAHEAD_MINUTES", "90"))
    now = _business_now()
    client = ApiFootballClient(api_key=api_key)
    matched = unmatched = waiting = recent = collected = 0
    provider_errors: list[dict[str, Any]] = []
    processing_errors: list[str] = []
    try:
        with get_db() as conn:
            matches = load_supported_matches(
                conn, start_time=now, end_time=now + timedelta(minutes=lookahead)
            )
            if not matches:
                return dict(
                    status="ok",
                    quality_status="not_due",
                    note="no supported matches in pre-match window",
                    window_minutes=lookahead,
                    api_calls_used=0,
                )
            aliases = load_api_aliases(conn)
            dates: dict[str, list[dict]] = {}
            for match in matches:
                dates.setdefault(match["kickoff_time"].date().isoformat(), []).append(match)
            for day, day_matches in dates.items():
                due = [m for m in day_matches if not _has_recent_lineup_checks(conn, m)]
                recent += len(day_matches) - len(due)
                if not due:
                    continue
                try:
                    fixtures = client.get_fixtures(date=day)
                    if client.last_response_meta.get("errors"):
                        raise ValueError("fixture discovery rejected")
                except Exception as exc:
                    conn.rollback()
                    provider_errors.append(
                        dict(endpoint="fixtures", date=day, reason=type(exc).__name__)
                    )
                    if not dry_run:
                        for match in due:
                            if not record_failed_player_query(
                                conn, match=match, domain="lineup", error=exc
                            ):
                                processing_errors.append(
                                    f"match {match['id']}: failure_receipt_unavailable"
                                )
                    continue
                for match in due:
                    fixture = find_matching_fixture(match, fixtures, aliases)
                    if fixture is None or not fixture.get("fixture", {}).get("id"):
                        unmatched += 1
                        continue
                    matched += 1
                    fixture_id = int(fixture["fixture"]["id"])
                    try:
                        details = client.get_fixtures(fixture_id=fixture_id)
                        if client.last_response_meta.get("errors"):
                            raise ValueError("fixture detail rejected")
                        if (
                            len(details) != 1
                            or details[0].get("fixture", {}).get("id") != fixture_id
                        ):
                            raise ValueError("fixture detail identity is absent or mismatched")
                        lineups = details[0].get("lineups")
                        if not isinstance(lineups, list):
                            raise ValueError("fixture lineups require an explicit list")
                        acquired = datetime.now(UTC)
                        if dry_run:
                            continue
                        resolved = []
                        seen = set()
                        teams = {match["home_team_id"], match["away_team_id"]}
                        for data in lineups:
                            if not isinstance(data, dict):
                                raise ValueError("lineup team requires an object")
                            team_id = aliases.get(str(data.get("team", {}).get("name") or ""))
                            if team_id is None or team_id not in teams or team_id in seen:
                                raise ValueError("lineup team is unmatched or duplicated")
                            seen.add(team_id)
                            resolved.append((team_id, data))
                        incomplete = False
                        for team_id, data in resolved:
                            if _process_lineup(
                                conn,
                                match["id"],
                                data,
                                team_id,
                                _now(),
                                api_fixture_id=fixture_id,
                                acquired_at=acquired,
                            ):
                                collected += 1
                            else:
                                incomplete = True
                        for team_id in sorted(teams - seen):
                            record_lineup_status(
                                conn,
                                match_id=match["id"],
                                team_id=team_id,
                                api_fixture_id=fixture_id,
                                acquired_at=acquired,
                                status=FactStatus.NOT_PUBLISHED,
                            )
                        if teams - seen:
                            conn.commit()
                            incomplete = True
                        waiting += int(incomplete)
                    except Exception as exc:
                        conn.rollback()
                        if not dry_run and not record_failed_player_query(
                            conn, match=match, domain="lineup", error=exc
                        ):
                            processing_errors.append(
                                f"match {match['id']}: failure_receipt_unavailable"
                            )
                        processing_errors.append(f"match {match['id']}: {type(exc).__name__}")
    finally:
        client.close()
    quality = (
        "degraded"
        if provider_errors or processing_errors or unmatched
        else "waiting"
        if waiting
        else "recently_checked"
        if recent
        else "healthy"
    )
    return dict(
        status="dry_run" if dry_run else "ok",
        quality_status=quality,
        quality_note="部分比赛仅有近期采集回执，本轮未重新核实首发完整度" if recent else "",
        window_minutes=lookahead,
        matches_supported=len(matches),
        matches_matched=matched,
        matches_unmatched=unmatched,
        matches_waiting_lineup=waiting,
        matches_already_complete=0,
        matches_recently_checked=recent,
        lineups_collected=collected,
        provider_errors=provider_errors,
        processing_errors=processing_errors,
        api_calls_used=client.call_count_today,
    )


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
