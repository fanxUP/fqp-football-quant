"""P104 source facts and legacy projections in a caller-owned transaction.

This adapter neither approves source coverage nor calls providers. Numeric
strength/absence heuristics in old projections are not source fact values.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from scripts.data_contracts import (
    AcquisitionStatus,
    FactStatus,
    LineupStatus,
    PlayerAvailabilityStatus,
    to_utc,
)
from scripts.feature_storage import (
    store_match_lineup_player,
    store_match_lineup_snapshot,
    store_player_availability_snapshot,
    store_team_squad_snapshot,
)
from scripts.observation_storage import append_observation, record_acquisition_failure

CHECK_FRESHNESS = timedelta(minutes=30)
_SHA256 = re.compile(r"^[a-f0-9]{64}$")


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
    if domain not in {"lineup", "injuries", "appearance"}:
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


def store_actual_appearance_observations(conn: Any, facts: dict) -> dict[str, dict]:
    """Append both teams' directly reported minutes in the caller's transaction.

    The complete payload is validated before the first write. No freshness
    expiry is applied to historical appearances, and this function never
    commits or performs provider I/O.
    """
    if not isinstance(facts, dict):
        raise ValueError("appearance facts must be an object")
    match_id = facts.get("match_id")
    fixture_id = facts.get("api_fixture_id")
    duration = facts.get("duration_bound_minutes")
    source_hash = facts.get("source_response_sha256")
    acquired_at = _source_timestamp_json(facts.get("acquired_at"), "acquired_at")
    if acquired_at is None:
        raise ValueError("appearance facts require a source acquisition timestamp")
    if type(match_id) is not int or match_id <= 0:
        raise ValueError("appearance facts require a canonical official match ID")
    if type(fixture_id) is not int or fixture_id <= 0:
        raise ValueError("appearance facts require a positive API fixture ID")
    if facts.get("fixture_link_status") != "linked":
        raise ValueError("appearance facts require a linked fixture")
    if facts.get("match_status") not in {"FT", "AET", "PEN"}:
        raise ValueError("appearance facts require an explicitly finished match")
    if type(duration) is not int or not 1 <= duration <= 135:
        raise ValueError("appearance facts require a bounded finished-match duration")
    if not isinstance(source_hash, str) or not _SHA256.fullmatch(source_hash):
        raise ValueError("appearance facts require a source response SHA-256")
    home_team_id = facts.get("home_team_id")
    away_team_id = facts.get("away_team_id")
    if (
        type(home_team_id) is not int
        or home_team_id <= 0
        or type(away_team_id) is not int
        or away_team_id <= 0
        or home_team_id == away_team_id
    ):
        raise ValueError("appearance facts require distinct canonical home and away teams")
    teams = facts.get("teams")
    if not isinstance(teams, list) or len(teams) != 2:
        raise ValueError("appearance facts require both fixture teams")

    normalized: dict[str, dict] = {}
    all_source_player_ids: set[str] = set()
    all_canonical_player_ids: set[int] = set()
    for team in teams:
        if not isinstance(team, dict) or team.get("side") not in {"home", "away"}:
            raise ValueError("appearance team requires an explicit home/away side")
        side = team["side"]
        if side in normalized:
            raise ValueError("appearance facts contain a duplicate team side")
        expected_team_id = home_team_id if side == "home" else away_team_id
        team_id = team.get("team_id")
        api_team_id = team.get("api_team_id")
        if type(team_id) is not int or team_id != expected_team_id:
            raise ValueError("appearance team does not match the official home/away identity")
        if type(api_team_id) is not int or api_team_id <= 0:
            raise ValueError("appearance team requires a positive source team ID")
        players = team.get("players")
        if not isinstance(players, list) or len(players) > 64:
            raise ValueError("appearance players must be a bounded list")
        source_count = team.get("source_reported_player_count")
        missing_count = team.get("missing_minutes_count")
        unresolved_count = team.get("unresolved_player_count")
        unresolved_ids = team.get("unresolved_source_player_ids")
        if (
            type(source_count) is not int
            or not 0 <= source_count <= 64
            or type(missing_count) is not int
            or not 0 <= missing_count <= 64
            or type(unresolved_count) is not int
            or not 0 <= unresolved_count <= 64
        ):
            raise ValueError("appearance coverage counts must be bounded")
        if (
            not isinstance(unresolved_ids, list)
            or len(unresolved_ids) != unresolved_count
            or any(
                not isinstance(source_id, str) or not source_id.isdecimal()
                for source_id in unresolved_ids
            )
            or len(set(unresolved_ids)) != len(unresolved_ids)
        ):
            raise ValueError("appearance unresolved source player IDs are invalid")
        if set(unresolved_ids) & all_source_player_ids:
            raise ValueError("appearance source player cannot be duplicated across fixture teams")
        seen_source_ids: set[str] = set()
        player_facts: list[dict] = []
        for player in players:
            if not isinstance(player, dict):
                raise ValueError("appearance player fact must be an object")
            source_player_id = player.get("source_player_id")
            player_id = player.get("player_id")
            minutes = player.get("minutes")
            if (
                not isinstance(source_player_id, str)
                or not source_player_id.isdecimal()
                or source_player_id in seen_source_ids
                or source_player_id in all_source_player_ids
            ):
                raise ValueError("appearance fact requires a distinct source player ID")
            if (
                type(player_id) is not int
                or player_id <= 0
                or player_id in all_canonical_player_ids
            ):
                raise ValueError("appearance fact requires a distinct canonical player ID")
            if type(minutes) is not int or not 0 <= minutes <= duration:
                raise ValueError("appearance minutes must be a bounded non-negative integer")
            if (
                player.get("source_reported") is not True
                or player.get("derivation") != "direct_source_field"
            ):
                raise ValueError("appearance minutes must be explicitly reported by the source")
            seen_source_ids.add(source_player_id)
            all_source_player_ids.add(source_player_id)
            all_canonical_player_ids.add(player_id)
            player_facts.append(
                {
                    "source_player_id": source_player_id,
                    "player_id": player_id,
                    "minutes": minutes,
                    "source_reported": True,
                    "derivation": "direct_source_field",
                }
            )
        if set(unresolved_ids) & seen_source_ids:
            raise ValueError("appearance source player cannot be both resolved and unresolved")
        if (
            source_count < len(player_facts)
            or source_count < missing_count
            or source_count < unresolved_count
        ):
            raise ValueError("appearance coverage counts exceed the source response")
        all_source_player_ids.update(unresolved_ids)
        normalized[side] = {
            "team_id": team_id,
            "api_team_id": api_team_id,
            "players": sorted(player_facts, key=lambda item: item["source_player_id"]),
            "source_reported_player_count": source_count,
            "missing_minutes_count": missing_count,
            "unresolved_player_count": unresolved_count,
            "unresolved_source_player_ids": sorted(unresolved_ids),
        }
    if set(normalized) != {"home", "away"}:
        raise ValueError("appearance facts require exactly one home and one away team")
    result: dict[str, dict] = {}
    for side in ("home", "away"):
        team = normalized[side]
        evidence = {
            "adapter_version": "api-football-appearance/v1",
            "api_fixture_id": fixture_id,
            "api_team_id": team["api_team_id"],
            "source_reported": True,
            "derivation": "direct_source_field",
            "source_response_sha256": source_hash,
            "source_reported_player_count": team["source_reported_player_count"],
            "missing_minutes_count": team["missing_minutes_count"],
            "unresolved_player_count": team["unresolved_player_count"],
            "unresolved_source_player_ids": team["unresolved_source_player_ids"],
        }
        value = (
            {
                "side": side,
                "team_id": team["team_id"],
                "api_team_id": team["api_team_id"],
                "api_fixture_id": fixture_id,
                "match_status": facts["match_status"],
                "duration_bound_minutes": duration,
                "players": team["players"],
                "source_reported_player_count": team["source_reported_player_count"],
                "missing_minutes_count": team["missing_minutes_count"],
                "unresolved_player_count": team["unresolved_player_count"],
            }
            if team["players"]
            else None
        )
        ref = append_observation(
            conn,
            **team_stream(match_id, team["team_id"], "appearance"),
            fact_status=FactStatus.VALUE if value is not None else FactStatus.UNKNOWN,
            value=value,
            acquired_at=datetime.fromisoformat(acquired_at),
            verified_at=datetime.fromisoformat(acquired_at),
            evidence=evidence,
        )
        result[side] = ref
    return result


def store_lineup_observation(
    conn: Any,
    snapshot: dict,
    players: list[dict],
    *,
    api_fixture_id: int,
    acquired_at: datetime,
) -> int:
    """Store one complete team roster/header/fact; no commit or rollback here."""
    raw_lineup_status = snapshot.get("lineup_type")
    if not isinstance(raw_lineup_status, str):
        raise ValueError("lineup requires an explicit supported status")
    try:
        lineup_status = LineupStatus(raw_lineup_status)
    except ValueError as exc:
        raise ValueError("lineup requires an explicit supported status") from exc
    if lineup_status is not LineupStatus.CONFIRMED:
        raise ValueError("only confirmed lineups may enter the confirmed roster projection")
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
            lineup_status=lineup_status.value,
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


def _source_timestamp_json(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError(f"source {field} must be an ISO timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"source {field} must include a timezone")
    return to_utc(parsed).isoformat()


def _source_date_json(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        raise ValueError(f"source {field} must be a calendar date, not a timestamp")
    if isinstance(value, date):
        parsed = value
    elif isinstance(value, str):
        parsed = date.fromisoformat(value)
    else:
        raise ValueError(f"source {field} must be an ISO calendar date")
    return parsed.isoformat()


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
                availability_status=PlayerAvailabilityStatus(
                    p.get("availability_status", PlayerAvailabilityStatus.UNKNOWN.value)
                ).value,
                reported_type=p["injury_type"],
                reported_reason=p["injury_body_part"],
                effective_at=_source_timestamp_json(p.get("source_effective_at"), "effective_at"),
                published_at=_source_timestamp_json(p.get("source_published_at"), "published_at"),
                expected_return_date=_source_date_json(
                    p.get("expected_return_date"), "expected_return_date"
                ),
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
