"""当日比赛级伤停采集任务。

使用 API-Football fixture injury 接口，不再把免费套餐可查的
2024 历史赛季伤停误用于当前比赛。查询成功但无记录时保留覆盖未知回执；只有明确覆盖证据才能确认无记录。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.api_football_player import get_or_create_player
from scripts.business_time import business_now_naive as _business_now
from scripts.business_time import business_now_naive_iso as _now
from scripts.data_contracts import PlayerAvailabilityStatus, to_utc
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


def _extract_injury_fields(injury: dict[str, Any]) -> tuple[str, str, str]:
    """兼容当前 fixture 响应和旧 league 响应的伤停字段。"""
    metadata = _extract_injury_observation_metadata(injury)
    return metadata["availability_status"], metadata["injury_type"], metadata["reason"]


def _source_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized_source_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _explicit_status(text: str, *, allow_medical_reason: bool) -> PlayerAvailabilityStatus | None:
    normalized = _normalized_source_text(text)
    tokens = set(normalized.split())
    if not normalized or {"no", "not", "without", "uninjured"}.intersection(tokens):
        return None
    if any(token.startswith("suspend") for token in tokens):
        return PlayerAvailabilityStatus.SUSPENDED
    if "doubtful" in tokens or "questionable" in tokens:
        return PlayerAvailabilityStatus.DOUBTFUL
    if normalized in {"returned", "return", "recovered", "available", "fit"}:
        return PlayerAvailabilityStatus.RETURNED
    if {"injury", "injuries", "injured"}.intersection(tokens):
        return PlayerAvailabilityStatus.INJURED
    if allow_medical_reason and {
        "bruise",
        "bruised",
        "concussion",
        "dislocation",
        "fracture",
        "fractured",
        "sprain",
        "sprained",
        "strain",
        "strained",
        "tear",
        "torn",
    }.intersection(tokens):
        return PlayerAvailabilityStatus.INJURED
    return None


def _availability_status(injury_type: str, reason: str) -> PlayerAvailabilityStatus:
    """Map explicit status values; API-Football's Missing Fixture is not a diagnosis."""
    typed_status = _explicit_status(injury_type, allow_medical_reason=False)
    if typed_status is not None:
        return typed_status
    if _normalized_source_text(injury_type) != "missing fixture":
        return PlayerAvailabilityStatus.UNKNOWN
    reason_status = _explicit_status(reason, allow_medical_reason=True)
    if reason_status in {
        PlayerAvailabilityStatus.SUSPENDED,
        PlayerAvailabilityStatus.INJURED,
    }:
        return reason_status
    return PlayerAvailabilityStatus.UNKNOWN


def _explicit_source_timestamp(injury: dict[str, Any], field: str) -> str | None:
    raw_legacy = injury.get("injury")
    legacy = raw_legacy if isinstance(raw_legacy, dict) else {}
    value = injury.get(field)
    if value is None:
        value = legacy.get(field)
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise ValueError(f"source {field} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"source {field} must include a timezone")
    return to_utc(parsed).isoformat()


def _explicit_expected_return_date(injury: dict[str, Any]) -> str | None:
    raw_player = injury.get("player")
    raw_legacy = injury.get("injury")
    player: dict[str, Any] = raw_player if isinstance(raw_player, dict) else {}
    legacy: dict[str, Any] = raw_legacy if isinstance(raw_legacy, dict) else {}
    value = injury.get("expected_return_date")
    if value is None:
        value = player.get("expected_return_date")
    if value is None:
        value = legacy.get("expected_return_date")
    if value is None or value == "":
        return None
    if isinstance(value, str):
        parsed = date.fromisoformat(value.strip())
    elif isinstance(value, date) and not isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError("source expected_return_date must be an ISO calendar date")
    return parsed.isoformat()


def _extract_injury_observation_metadata(injury: dict[str, Any]) -> dict[str, Any]:
    """Normalize explicit source facts; absent values remain unknown/null."""
    raw_player = injury.get("player")
    raw_legacy = injury.get("injury")
    player: dict[str, Any] = raw_player if isinstance(raw_player, dict) else {}
    legacy: dict[str, Any] = raw_legacy if isinstance(raw_legacy, dict) else {}
    injury_type = _source_text(player.get("type") or legacy.get("type"))
    reason = _source_text(player.get("reason") or legacy.get("reason"))
    return {
        "availability_status": _availability_status(injury_type, reason).value,
        "injury_type": injury_type,
        "reason": reason,
        "effective_at": _explicit_source_timestamp(injury, "effective_at"),
        "published_at": _explicit_source_timestamp(injury, "published_at"),
        "expected_return_date": _explicit_expected_return_date(injury),
    }


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
            metadata = _extract_injury_observation_metadata(injury)
            status = metadata["availability_status"]
            injury_type = metadata["injury_type"]
            reason = metadata["reason"]
            expected_return_date = (
                date.fromisoformat(metadata["expected_return_date"])
                if metadata["expected_return_date"] is not None
                else None
            )
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
                    expected_return_date=expected_return_date,
                    source_effective_at=metadata["effective_at"],
                    source_published_at=metadata["published_at"],
                    is_suspended=status == "suspended",
                    suspension_reason=reason if status == "suspended" else "",
                    source_name="api-football",
                    source_confidence=0.90,
                    recent_minutes_share=None,
                    team_market_value_share=None,
                    position_importance_score=None,
                    replacement_quality_score=None,
                    absence_impact_score=None,
                    raw_json=dict(
                        injury,
                        official_match_id=match["id"],
                        api_fixture_id=api_fixture_id,
                        derived_fields_version="source-players/v2",
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
                    key_absence_count=None,
                    squad_health_score=None,
                    data_confidence=0.90,
                    raw_json=dict(
                        source_result_count=len(injuries),
                        derived_fields_version="source-players/v2",
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
