"""P104 source facts and legacy projections in a caller-owned transaction.

This adapter neither approves source coverage nor calls providers. Numeric
strength/absence heuristics in old projections are not source fact values.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.data_contracts import AcquisitionStatus, FactStatus, to_utc
from scripts.feature_storage import (
    store_match_lineup_player,
    store_match_lineup_snapshot,
    store_player_availability_snapshot,
    store_team_squad_snapshot,
)
from scripts.observation_storage import append_observation, record_acquisition_failure

CHECK_FRESHNESS = timedelta(minutes=30)


def begin_player_group(conn: Any) -> None:
    """Serialize these bounded DB-only publications before creating identities.

    Both collectors use this order before per-stream locks, preventing new
    shared player-code races/deadlocks across overlapping rosters. No HTTP
    request may run while holding this transaction lock.
    """
    if conn.autocommit is True:
        raise ValueError("player group requires a caller-owned transaction")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(104, 3)")


def legacy_snapshot_time(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return (
        to_utc(parsed, naive_timezone="Asia/Shanghai")
        .astimezone(ZoneInfo("Asia/Shanghai"))
        .replace(tzinfo=None)
    )


def team_stream(match_id: int, team_id: int, domain: str) -> dict:
    if type(match_id) is not int or match_id <= 0 or type(team_id) is not int or team_id <= 0:
        raise ValueError("player observation requires canonical match/team IDs")
    if domain not in {"lineup", "injuries"}:
        raise ValueError("unsupported player observation domain")
    return dict(
        match_id=match_id, source_id="api_football", domain=domain, subject_key=f"team:{team_id}"
    )


def _evidence(api_fixture_id: int, coverage_evidence: str | None = None) -> dict:
    if type(api_fixture_id) is not int or api_fixture_id <= 0:
        raise ValueError("player observation requires a matched API fixture ID")
    if coverage_evidence is not None and (
        not isinstance(coverage_evidence, str)
        or not coverage_evidence.strip()
        or len(coverage_evidence) > 256
    ):
        raise ValueError("coverage requires a bounded trusted evidence reference")
    return dict(
        adapter_version="api-football-players/v1",
        api_fixture_id=api_fixture_id,
        coverage_complete=coverage_evidence is not None,
        coverage_evidence=coverage_evidence,
    )


def record_lineup_status(
    conn: Any,
    *,
    match_id: int,
    team_id: int,
    api_fixture_id: int,
    acquired_at: datetime,
    status: FactStatus,
    source_response: dict | None = None,
) -> dict:
    if status not in {FactStatus.NOT_PUBLISHED, FactStatus.UNKNOWN}:
        raise ValueError("incomplete lineup requires an explicit unknown/publication status")
    evidence = _evidence(api_fixture_id)
    if source_response is not None:
        evidence["source_response"] = source_response
    return append_observation(
        conn,
        **team_stream(match_id, team_id, "lineup"),
        fact_status=status,
        value=None,
        acquired_at=acquired_at,
        verified_at=acquired_at,
        valid_until=acquired_at + CHECK_FRESHNESS,
        evidence=evidence,
    )


def store_lineup_observation(
    conn: Any,
    snapshot: dict,
    players: list[dict],
    *,
    api_fixture_id: int,
    acquired_at: datetime,
) -> int:
    """Store one complete team roster/header/fact; no commit or rollback here."""
    if (
        len(players) > 64
        or sum(p["is_starting"] for p in players) != 11
        or len({p["player_id"] for p in players}) != len(players)
    ):
        raise ValueError("confirmed lineup requires eleven distinct starters and bounded players")
    source_players = [
        {
            key: p[key]
            for key in ("player_id", "source_player_id", "is_starting", "is_substitute", "position")
        }
        for p in players
    ]
    source_players.sort(key=lambda p: (not p["is_starting"], p["source_player_id"]))
    evidence = _evidence(api_fixture_id, "reported-eleven-unique-starters/v1")
    ref = append_observation(
        conn,
        **team_stream(snapshot["match_id"], snapshot["team_id"], "lineup"),
        fact_status=FactStatus.VALUE,
        value=dict(
            formation=snapshot.get("formation"),
            players=source_players,
            team_id=snapshot["team_id"],
            api_fixture_id=api_fixture_id,
        ),
        acquired_at=acquired_at,
        verified_at=acquired_at,
        valid_until=acquired_at + CHECK_FRESHNESS,
        evidence=evidence,
    )
    projection = dict(
        snapshot,
        raw_json={**snapshot.get("raw_json", {}), "observation_revision_id": ref["revision_id"]},
    )
    lineup_id = store_match_lineup_snapshot(conn, projection, commit=False)
    if not lineup_id:
        raise ValueError("lineup projection did not return its ID")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM match_lineup_players WHERE lineup_snapshot_id=%s", (lineup_id,))
    for player in players:
        store_match_lineup_player(conn, dict(player, lineup_snapshot_id=lineup_id), commit=False)
    return lineup_id


def store_injury_observations(
    conn: Any,
    *,
    match_id: int,
    api_fixture_id: int,
    summaries: list[dict],
    players: list[dict],
    acquired_at: datetime,
    coverage_evidence: str | None = None,
) -> None:
    """One fixture's reported injuries and two team receipts; caller commits all."""
    if len(summaries) != 2 or len({s["team_id"] for s in summaries}) != 2 or len(players) > 128:
        raise ValueError("fixture injuries require two teams and a bounded player list")
    evidence = _evidence(api_fixture_id, coverage_evidence)
    teams = {s["team_id"] for s in summaries}
    if any(p["team_id"] not in teams for p in players):
        raise ValueError("injury player belongs to another team")
    for summary in sorted(summaries, key=lambda s: s["team_id"]):
        team_id = summary["team_id"]
        selected = [p for p in players if p["team_id"] == team_id]
        facts = [
            dict(
                player_id=p["player_id"],
                source_player_id=p["source_player_id"],
                reported_type=p["injury_type"],
                reported_reason=p["injury_body_part"],
            )
            for p in selected
        ]
        facts.sort(key=lambda p: p["source_player_id"])
        status = (
            FactStatus.VALUE
            if facts
            else FactStatus.CONFIRMED_ABSENT
            if coverage_evidence
            else FactStatus.UNKNOWN
        )
        ref = append_observation(
            conn,
            **team_stream(match_id, team_id, "injuries"),
            fact_status=status,
            value=dict(players=facts, team_id=team_id, api_fixture_id=api_fixture_id)
            if facts
            else None,
            acquired_at=acquired_at,
            verified_at=acquired_at,
            valid_until=acquired_at + CHECK_FRESHNESS,
            evidence=dict(evidence, source_reported_count=len(facts)),
        )
        raw = dict(
            summary.get("raw_json", {}),
            observation_type="fixture_injuries",
            official_match_id=match_id,
            api_fixture_id=api_fixture_id,
            coverage_complete=coverage_evidence is not None,
            observation_revision_id=ref["revision_id"],
        )
        store_team_squad_snapshot(conn, dict(summary, raw_json=raw), commit=False)
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM player_availability_snapshots WHERE team_id=%s AND source_name='api-football' AND raw_json->>'official_match_id'=%s",
                (team_id, str(match_id)),
            )
        for player in selected:
            store_player_availability_snapshot(conn, player, commit=False)


def record_player_acquisition_failure(
    conn: Any,
    *,
    match_id: int,
    team_ids: list[int],
    domain: str,
    status: AcquisitionStatus,
    acquired_at: datetime,
) -> None:
    for team_id in sorted(set(team_ids)):
        record_acquisition_failure(
            conn, **team_stream(match_id, team_id, domain), status=status, acquired_at=acquired_at
        )


def has_fresh_team_checks(conn: Any, *, match_id: int, team_ids: list[int], domain: str) -> bool:
    """Throttle only recent checked responses, including explicit unknowns.

    This is a request freshness check, not a claim of full source coverage.
    Old projection-only rows cannot suppress a new observation indefinitely.
    """
    if len(team_ids) != 2 or len(set(team_ids)) != 2:
        return False
    streams = [team_stream(match_id, team_id, domain) for team_id in team_ids]
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM observation_streams s JOIN LATERAL (
                SELECT acquisition_status,valid_until,available_at FROM observation_checks
                WHERE stream_id=s.id ORDER BY id DESC LIMIT 1
            ) c ON true
            WHERE s.match_id=%s AND s.source_id='api_football' AND s.domain=%s
              AND s.subject_key=ANY(%s) AND c.acquisition_status='success'
              AND c.available_at<=clock_timestamp() AND c.valid_until>clock_timestamp()""",
            (match_id, domain, [s["subject_key"] for s in streams]),
        )
        return int(cur.fetchone()[0]) == 2


def record_failed_player_query(conn: Any, *, match: dict, domain: str, error: Exception) -> bool:
    """Best-effort sanitized failure receipt; optional collection stays bounded."""
    from scripts.api_football_client import ApiFootballRateLimitError
    from scripts.request_quota import QuotaDenied, QuotaUnavailable
    from scripts.request_transport import ProviderRequestError

    status = AcquisitionStatus.FAILED
    if isinstance(error, ApiFootballRateLimitError):
        status = AcquisitionStatus.QUOTA_EXHAUSTED
    elif isinstance(error, QuotaUnavailable):
        status = AcquisitionStatus.UNAVAILABLE
    elif isinstance(error, (QuotaDenied, ProviderRequestError)):
        reason = error.reason
        if reason in {
            "daily_exhausted",
            "rate_limited",
            "daily_budget",
            "provider_daily_budget",
            "environment_budget",
            "priority_reserved",
            "minute_budget",
            "provider_minute_budget",
            "cooldown",
            "minimum_interval",
        }:
            status = AcquisitionStatus.QUOTA_EXHAUSTED
        elif reason in {
            "authentication_denied",
            "plan_denied",
            "endpoint_denied",
            "policy_disabled",
        }:
            status = AcquisitionStatus.FORBIDDEN
        else:
            status = AcquisitionStatus.UNAVAILABLE
    try:
        record_player_acquisition_failure(
            conn,
            match_id=match["id"],
            team_ids=[match["home_team_id"], match["away_team_id"]],
            domain=domain,
            status=status,
            acquired_at=datetime.now(UTC),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
