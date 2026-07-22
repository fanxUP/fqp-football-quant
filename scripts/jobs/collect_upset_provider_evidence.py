"""Collect auxiliary in-match events and post-match statistics for cold results."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from psycopg2.extras import RealDictCursor

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.features.api_football_fixture_matcher import (
    find_matching_fixture,
    load_api_aliases,
)
from scripts.upset.evidence import evidence_record
from scripts.upset.provider_evidence import (
    build_event_evidence_values,
    build_statistics_evidence_values,
)
from scripts.upset.review_storage import insert_evidence


def _business_now() -> datetime:
    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone_name)).replace(tzinfo=None)


def _load_pending_events(conn: Any, *, limit: int, lookback_days: int) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (event.id)
                event.id AS upset_event_id,
                event.match_id,
                match.business_date,
                match.kickoff_time,
                match.home_team_name,
                match.away_team_name,
                home_alias.team_id AS home_team_id,
                away_alias.team_id AS away_team_id,
                substring(competition.competition_code FROM 13)::integer AS api_league_id
            FROM upset_events event
            JOIN official_matches match ON match.id = event.match_id
            JOIN team_aliases home_alias
              ON home_alias.source_name = 'sporttery'
             AND home_alias.alias_name = match.home_team_name
            JOIN team_aliases away_alias
              ON away_alias.source_name = 'sporttery'
             AND away_alias.alias_name = match.away_team_name
            JOIN competition_seasons competition_season ON TRUE
            JOIN seasons season
              ON season.id = competition_season.season_id
             AND match.kickoff_time::date BETWEEN season.start_date AND season.end_date
            JOIN competitions competition
              ON competition.id = competition_season.competition_id
             AND competition.competition_name_cn = match.league_name
             AND competition.competition_code LIKE 'apifootball:%%'
            WHERE event.detection_status = 'detected'
              AND event.business_date >= CURRENT_DATE - %s
              AND NOT EXISTS (
                    SELECT 1 FROM upset_factor_evidence evidence
                    WHERE evidence.upset_event_id = event.id
                      AND evidence.factor_category = 'provider_capture'
                      AND evidence.source_type = 'api_football_match_data'
              )
            ORDER BY event.id, season.is_current DESC, season.start_date DESC
            LIMIT %s
            """,
            (lookback_days, limit),
        )
        return [dict(row) for row in cur.fetchall()]


def _canonical_record(
    event: dict[str, Any],
    value: dict[str, Any],
    *,
    fixture_id: int,
    observed_at: datetime,
) -> dict[str, Any]:
    code = str(value["factor_code"])
    return evidence_record(
        event_id=int(event["upset_event_id"]),
        category=str(value["factor_category"]),
        code=code,
        value=dict(value["factor_value_json"]),
        phase=str(value["evidence_phase"]),
        source_type="api_football_match_data",
        source_reference=f"api_football_fixture:{fixture_id}:{code}",
        observed_at=observed_at,
        available_at=observed_at,
        kickoff_time=event["kickoff_time"],
        confidence=0.9,
        verification_status="verified",
    )


def _capture_record(
    event: dict[str, Any],
    *,
    fixture_id: int,
    event_count: int,
    statistics_count: int,
    observed_at: datetime,
) -> dict[str, Any]:
    return evidence_record(
        event_id=int(event["upset_event_id"]),
        category="provider_capture",
        code="api_football_match_data_capture",
        value={
            "text": "赛后辅助比赛数据已完成采集",
            "fixture_id": fixture_id,
            "event_count": event_count,
            "statistics_count": statistics_count,
        },
        phase="postmatch",
        source_type="api_football_match_data",
        source_reference=f"api_football_fixture:{fixture_id}:capture",
        observed_at=observed_at,
        available_at=observed_at,
        kickoff_time=event["kickoff_time"],
        confidence=0.9,
        verification_status="verified",
    )


def _run_impl(*, limit: int | None = None, lookback_days: int | None = None) -> dict[str, Any]:
    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {
            "status": "skipped",
            "quality_status": "unavailable",
            "reason": "API_FOOTBALL_KEY_NOT_CONFIGURED",
            "api_calls_used": 0,
        }

    row_limit = limit or int(os.getenv("UPSET_PROVIDER_EVIDENCE_LIMIT", "20"))
    days = lookback_days or int(os.getenv("UPSET_PROVIDER_EVIDENCE_LOOKBACK_DAYS", "14"))
    client = ApiFootballClient(api_key=api_key)
    matched = 0
    unmatched = 0
    inserted = 0
    completed = 0
    errors: list[str] = []
    try:
        with get_db() as conn:
            pending = _load_pending_events(conn, limit=row_limit, lookback_days=days)
            if not pending:
                return {
                    "status": "ok",
                    "quality_status": "not_due",
                    "events_pending": 0,
                    "api_calls_used": 0,
                }
            aliases = load_api_aliases(conn)
            by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for event in pending:
                by_date[event["kickoff_time"].date().isoformat()].append(event)

            for match_date, day_events in by_date.items():
                try:
                    fixtures = client.get_fixtures(date=match_date)
                except Exception as exc:
                    errors.append(f"date {match_date}: {exc}")
                    continue
                for event in day_events:
                    fixture = find_matching_fixture(event, fixtures, aliases)
                    if fixture is None:
                        unmatched += 1
                        continue
                    matched += 1
                    fixture_data = fixture.get("fixture") or {}
                    fixture_id = int(fixture_data.get("id") or 0)
                    if not fixture_id:
                        unmatched += 1
                        matched -= 1
                        continue
                    try:
                        provider_events = client.get_fixture_events(fixture_id)
                        event_errors = client.last_response_meta.get("errors") or {}
                        if event_errors:
                            raise RuntimeError(f"events endpoint error: {event_errors}")
                        provider_statistics = client.get_fixture_statistics(fixture_id)
                        statistics_errors = client.last_response_meta.get("errors") or {}
                        if statistics_errors:
                            raise RuntimeError(f"statistics endpoint error: {statistics_errors}")
                        team_names = {
                            int((fixture.get("teams", {}).get("home") or {}).get("id") or 0): str(
                                event["home_team_name"]
                            ),
                            int((fixture.get("teams", {}).get("away") or {}).get("id") or 0): str(
                                event["away_team_name"]
                            ),
                        }
                        normalized = [
                            *build_event_evidence_values(
                                provider_events,
                                team_names_by_api_id=team_names,
                            ),
                            *build_statistics_evidence_values(
                                provider_statistics,
                                team_names_by_api_id=team_names,
                            ),
                        ]
                        observed_at = _business_now()
                        for value in normalized:
                            inserted += int(
                                insert_evidence(
                                    conn,
                                    _canonical_record(
                                        event,
                                        value,
                                        fixture_id=fixture_id,
                                        observed_at=observed_at,
                                    ),
                                )
                            )
                        inserted += int(
                            insert_evidence(
                                conn,
                                _capture_record(
                                    event,
                                    fixture_id=fixture_id,
                                    event_count=len(provider_events),
                                    statistics_count=len(provider_statistics),
                                    observed_at=observed_at,
                                ),
                            )
                        )
                        completed += 1
                    except Exception as exc:
                        errors.append(f"event {event['upset_event_id']}: {exc}")
            conn.commit()
    finally:
        client.close()

    quality_status = "healthy"
    if errors or unmatched:
        quality_status = "degraded"
    return {
        "status": "ok",
        "quality_status": quality_status,
        "events_pending": len(pending),
        "events_matched": matched,
        "events_unmatched": unmatched,
        "events_completed": completed,
        "evidence_inserted": inserted,
        "errors": errors,
        "api_calls_used": client.call_count_today,
    }


def run(*, limit: int | None = None, lookback_days: int | None = None) -> dict[str, Any]:
    run_id = start_tracked_job(
        "collect_upset_provider_evidence",
        "review_agent",
        {"limit": limit, "lookback_days": lookback_days},
    )
    try:
        result = _run_impl(limit=limit, lookback_days=lookback_days)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    print(run())
