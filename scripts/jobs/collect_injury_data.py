"""当日比赛级伤停采集任务。

使用 API-Football fixture injury 接口，不再把免费套餐可查的
2024 历史赛季伤停误用于当前比赛。查询成功但无记录时保留覆盖未知回执；只有明确覆盖证据才能确认无记录。
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.api_football_player import get_or_create_player
from scripts.business_time import business_now_naive as _business_now
from scripts.business_time import business_now_naive_iso as _now
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
    store_injury_observations,
)

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


def _get_or_create_player(conn: Any, player_data: dict[str, Any]) -> int | None:
    return get_or_create_player(conn, player_data, prefer_short_position=False, commit=False)


def _process_fixture_injuries(
    conn: Any,
    match: dict[str, Any],
    api_fixture_id: int,
    injuries: list[dict[str, Any]],
    alias_to_team_id: dict[str, int],
    snapshot_time: str | datetime,
    *,
    acquired_at: datetime | None = None,
    coverage_evidence: str | None = None,
) -> int:
    """Commit both team receipts, exact source facts and all player projections."""
    try:
        begin_player_group(conn)
        snapshot_time = legacy_snapshot_time(snapshot_time)
        if (
            not isinstance(injuries, list)
            or len(injuries) > 128
            or not match.get("competition_season_id")
        ):
            raise ValueError("injury query requires bounded rows and a resolved season")
        if len(json.dumps(injuries, allow_nan=False).encode()) > 65536:
            raise ValueError("injury response exceeds 64KiB")
        team_ids = {match["home_team_id"], match["away_team_id"]}
        if len(team_ids) != 2:
            raise ValueError("injury match requires two distinct teams")
        players = []
        seen = set()
        for injury in injuries:
            if not isinstance(injury, dict) or not isinstance(injury.get("player"), dict):
                raise ValueError("injury response requires player objects")
            if injury.get("fixture", {}).get("id", api_fixture_id) != api_fixture_id:
                raise ValueError("injury fixture identity mismatch")
            team_id = alias_to_team_id.get(str(injury.get("team", {}).get("name") or ""))
            source_player_id = injury["player"].get("id")
            if (
                team_id not in team_ids
                or type(source_player_id) is not int
                or source_player_id <= 0
                or source_player_id in seen
            ):
                raise ValueError("injury team/player is unresolved or duplicated")
            seen.add(source_player_id)
            player_id = _get_or_create_player(conn, injury["player"])
            if not player_id:
                raise ValueError("injury player identity unresolved")
            status, injury_type, reason = _extract_injury_fields(injury)
            importance = _position_importance(str(injury["player"].get("position") or ""))
            players.append(
                dict(
                    player_id=player_id,
                    source_player_id=source_player_id,
                    team_id=team_id,
                    competition_season_id=match["competition_season_id"],
                    snapshot_time=snapshot_time,
                    availability_status=status,
                    injury_type=injury_type,
                    injury_body_part=reason,
                    is_suspended=status == "suspended",
                    suspension_reason=reason if status == "suspended" else "",
                    source_name="api-football",
                    source_confidence=0.90,
                    recent_minutes_share=0.0,
                    team_market_value_share=0.0,
                    position_importance_score=importance,
                    replacement_quality_score=0.5,
                    absence_impact_score=importance * 85.0,
                    raw_json=dict(
                        injury,
                        official_match_id=match["id"],
                        api_fixture_id=api_fixture_id,
                        derived_fields_version="legacy-injury-heuristics/v1",
                    ),
                )
            )
        summaries = []
        for team_id in sorted(team_ids):
            counts = Counter(p["availability_status"] for p in players if p["team_id"] == team_id)
            summaries.append(
                dict(
                    team_id=team_id,
                    competition_season_id=match["competition_season_id"],
                    snapshot_time=snapshot_time,
                    injured_players_count=counts["injured"],
                    suspended_players_count=counts["suspended"],
                    doubtful_players_count=counts["doubtful"],
                    key_absence_count=0,
                    squad_health_score=max(
                        0.0, 100.0 - counts["injured"] * 8.0 - counts["suspended"] * 10.0
                    ),
                    data_confidence=0.90,
                    raw_json=dict(
                        source_result_count=len(injuries),
                        derived_fields_version="legacy-injury-heuristics/v1",
                    ),
                )
            )
        store_injury_observations(
            conn,
            match_id=match["id"],
            api_fixture_id=api_fixture_id,
            summaries=summaries,
            players=players,
            acquired_at=datetime.now(UTC) if acquired_at is None else acquired_at,
            coverage_evidence=coverage_evidence,
        )
        conn.commit()
        return len(players)
    except Exception:
        conn.rollback()
        raise


def _run_impl(dry_run: bool = False, business_date: date | None = None) -> dict[str, Any]:
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return dict(status="error", message="API_FOOTBALL_KEY not set")
    target = business_date or _business_now().date()
    start = datetime.combine(target, time.min)
    client = ApiFootballClient(api_key=api_key)
    matched = unmatched = recent = observations = collected = 0
    provider_errors: list[dict[str, Any]] = []
    processing_errors: list[str] = []
    try:
        with get_db() as conn:
            matches = load_supported_matches(
                conn, start_time=start, end_time=start + timedelta(days=1)
            )
            if not matches:
                return dict(
                    status="ok",
                    quality_status="not_due",
                    note="no supported selling matches for target date",
                    target_date=target.isoformat(),
                    api_calls_used=0,
                )
            aliases = load_api_aliases(conn)
            due = [
                m
                for m in matches
                if not has_fresh_team_checks(
                    conn,
                    match_id=m["id"],
                    team_ids=[m["home_team_id"], m["away_team_id"]],
                    domain="injuries",
                )
            ]
            recent = len(matches) - len(due)
            try:
                fixtures = client.get_fixtures(date=target.isoformat()) if due else []
                if due and client.last_response_meta.get("errors"):
                    raise ValueError("fixture discovery rejected")
            except Exception as exc:
                conn.rollback()
                provider_errors.append(dict(endpoint="fixtures", reason=type(exc).__name__))
                if not dry_run:
                    for match in due:
                        if not record_failed_player_query(
                            conn, match=match, domain="injuries", error=exc
                        ):
                            processing_errors.append(
                                f"match {match['id']}: failure_receipt_unavailable"
                            )
                due = []
            for match in due:
                fixture = find_matching_fixture(match, fixtures, aliases)
                if fixture is None or not fixture.get("fixture", {}).get("id"):
                    unmatched += 1
                    continue
                matched += 1
                fixture_id = int(fixture["fixture"]["id"])
                try:
                    rows = client.get_injuries(fixture=fixture_id)
                    if client.last_response_meta.get("errors"):
                        raise ValueError("injury query rejected")
                    if not dry_run:
                        count = _process_fixture_injuries(
                            conn,
                            match,
                            fixture_id,
                            rows,
                            aliases,
                            _now(),
                            acquired_at=datetime.now(UTC),
                        )
                        observations += 2
                        collected += count
                except Exception as exc:
                    conn.rollback()
                    if not dry_run and not record_failed_player_query(
                        conn, match=match, domain="injuries", error=exc
                    ):
                        processing_errors.append(
                            f"match {match['id']}: failure_receipt_unavailable"
                        )
                    processing_errors.append(f"match {match['id']}: {type(exc).__name__}")
    finally:
        client.close()
    quality = (
        "degraded" if provider_errors or processing_errors or unmatched else "coverage_unverified"
    )
    return dict(
        status="dry_run" if dry_run else "ok",
        quality_status=quality,
        target_date=target.isoformat(),
        matches_supported=len(matches),
        matches_matched=matched,
        matches_unmatched=unmatched,
        matches_already_observed=0,
        matches_recently_checked=recent,
        observations_stored=observations,
        injuries_collected=collected,
        coverage_verified=False,
        provider_errors=provider_errors,
        processing_errors=processing_errors,
        api_calls_used=client.call_count_today,
    )


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
