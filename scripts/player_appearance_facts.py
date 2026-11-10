"""Strict source-reported player minutes for one verified, finished fixture.

This module is a pure adapter: it does not perform HTTP requests or database
writes. Names, substitution events, and Titan's legacy derived minutes never
produce actual-minute values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

_FINISHED_REGULATION_MINUTES = {"FT": 90, "AET": 120, "PEN": 120}
_MAX_ADDED_MINUTES = 15
_SUBSTITUTION_MINUTE_TOLERANCE = 2


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _duration_bound(status: dict[str, Any]) -> tuple[str, int]:
    if not isinstance(status, dict):
        raise ValueError("fixture status must be an object")
    short = status.get("short")
    if not isinstance(short, str) or short not in _FINISHED_REGULATION_MINUTES:
        raise ValueError("fixture must have an explicitly supported finished status")

    regulation = _FINISHED_REGULATION_MINUTES[short]
    elapsed = status.get("elapsed")
    if elapsed is None:
        elapsed_minutes = regulation
    elif type(elapsed) is int and regulation <= elapsed <= regulation + _MAX_ADDED_MINUTES:
        elapsed_minutes = elapsed
    else:
        raise ValueError("finished fixture elapsed time is outside its supported duration")

    extra = status.get("extra")
    if extra is None:
        extra_minutes = 0
    elif type(extra) is int and 0 <= extra <= _MAX_ADDED_MINUTES:
        extra_minutes = extra
    else:
        raise ValueError("finished fixture extra time must be a bounded non-negative integer")

    duration = max(regulation + extra_minutes, elapsed_minutes)
    if duration > regulation + _MAX_ADDED_MINUTES:
        raise ValueError("finished fixture duration exceeds its supported upper bound")
    return short, duration


def _minutes(row: dict[str, Any], duration_bound: int) -> int | None:
    statistics = row.get("statistics")
    if statistics is None or statistics == []:
        return None
    if not isinstance(statistics, list) or len(statistics) != 1:
        raise ValueError("fixture player requires zero or one statistics record")
    statistic = statistics[0]
    if not isinstance(statistic, dict):
        raise ValueError("fixture player statistics record must be an object")
    games = statistic.get("games")
    if games is None:
        return None
    if not isinstance(games, dict):
        raise ValueError("fixture player games statistics must be an object")
    value = games.get("minutes")
    if value is None:
        return None
    if type(value) is not int or value < 0 or value > duration_bound:
        raise ValueError("reported minutes must be a bounded non-negative integer")
    return value


def _canonical_response_hash(
    fixture_summary: dict[str, Any],
    fixture_players: list[dict[str, Any]],
    substitution_events: list[dict[str, Any]] | None,
) -> str:
    try:
        serialized = json.dumps(
            {
                "fixture": fixture_summary,
                "players": fixture_players,
                "substitution_events": substitution_events,
            },
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source response must be finite JSON data") from exc
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _substitution_minutes(
    events: list[dict[str, Any]] | None,
    api_home_team_id: int,
    api_away_team_id: int,
    duration_bound: int,
) -> tuple[dict[tuple[int, int], list[int]], dict[tuple[int, int], list[int]]]:
    outgoing: dict[tuple[int, int], list[int]] = {}
    incoming: dict[tuple[int, int], list[int]] = {}
    if events is None:
        return outgoing, incoming
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("substitution events must be a list of objects")

    known_teams = {api_home_team_id, api_away_team_id}
    for event in events:
        if event.get("type") != "subst":
            continue
        team = event.get("team")
        time = event.get("time")
        player = event.get("player")
        substitute = event.get("assist")
        if (
            not isinstance(team, dict)
            or not isinstance(time, dict)
            or not isinstance(player, dict)
            or not isinstance(substitute, dict)
        ):
            raise ValueError("substitution event is missing its team, time, or player IDs")
        team_id = _positive_int(team.get("id"), "substitution team ID")
        if team_id not in known_teams:
            raise ValueError("substitution event belongs to an unmatched team")
        elapsed = time.get("elapsed")
        extra = time.get("extra")
        if type(elapsed) is not int or elapsed <= 0:
            raise ValueError("substitution event elapsed minute must be a positive integer")
        if extra is None:
            extra_minutes = 0
        elif type(extra) is int and 0 <= extra <= _MAX_ADDED_MINUTES:
            extra_minutes = extra
        else:
            raise ValueError("substitution event extra minute is invalid")
        minute = elapsed + extra_minutes
        if minute > duration_bound + _MAX_ADDED_MINUTES:
            raise ValueError("substitution event exceeds the bounded match duration")
        outgoing.setdefault(
            (team_id, _positive_int(player.get("id"), "outgoing player ID")), []
        ).append(minute)
        incoming.setdefault(
            (team_id, _positive_int(substitute.get("id"), "incoming player ID")), []
        ).append(minute)
    return outgoing, incoming


def _check_substitution_consistency(
    reported_minutes: dict[tuple[int, int], int | None],
    outgoing: dict[tuple[int, int], list[int]],
    incoming: dict[tuple[int, int], list[int]],
    duration_bound: int,
) -> None:
    for key in reported_minutes.keys() | outgoing.keys() | incoming.keys():
        minutes = reported_minutes.get(key)
        if minutes is None:
            continue
        exits = outgoing.get(key, [])
        entries = incoming.get(key, [])
        if len(exits) > 1 or len(entries) > 1:
            raise ValueError("multiple substitution events make player minutes ambiguous")
        if minutes == 0 and (exits or entries):
            raise ValueError("reported zero minutes contradict a substitution event")
        if any(minutes > minute + 1 for minute in exits):
            raise ValueError("reported minutes contradict a substitution-off event")
        if any(minutes > duration_bound - minute + 2 for minute in entries):
            raise ValueError("reported minutes contradict a substitution-on event")
        # Event times provide a bounded consistency check, never an estimate.
        # An incoming-only player may have been sent off later, so do not infer
        # a lower bound for that case. For a known exit, a much shorter source
        # value is impossible even allowing for minute-rounding differences.
        if exits:
            entry_minute = entries[0] if entries else 0
            expected_interval = exits[0] - entry_minute
            if expected_interval < 0:
                raise ValueError("substitution-off event precedes the player's entry")
            lower_bound = max(0, expected_interval - _SUBSTITUTION_MINUTE_TOLERANCE)
            upper_bound = expected_interval + _SUBSTITUTION_MINUTE_TOLERANCE
            if minutes < lower_bound or (entries and minutes > upper_bound):
                raise ValueError("reported minutes contradict the known substitution interval")


def build_actual_appearance_facts(
    *,
    official_match: dict[str, Any],
    fixture_summary: dict[str, Any],
    fixture_players: list[dict[str, Any]],
    resolve_player_id: Callable[[str], int | None],
    acquired_at: datetime,
    substitution_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build immutable-provenance facts from a direct fixture-player response.

    ``official_match`` is expected to come from a database query that already
    resolved the API fixture link; the parser additionally checks that link's
    status, IDs, and home/away direction against every supplied response.
    ``resolve_player_id`` must be the verified source-ID bridge. It is never
    called with a name.
    """
    required_match_fields = {
        "match_id",
        "api_fixture_id",
        "fixture_link_status",
        "home_team_id",
        "away_team_id",
        "api_home_team_id",
        "api_away_team_id",
    }
    if not isinstance(official_match, dict) or not required_match_fields <= official_match.keys():
        raise ValueError("official match requires a complete verified fixture binding")
    match_id = _positive_int(official_match["match_id"], "official match ID")
    fixture_id = _positive_int(official_match["api_fixture_id"], "API fixture ID")
    home_team_id = _positive_int(official_match["home_team_id"], "official home team ID")
    away_team_id = _positive_int(official_match["away_team_id"], "official away team ID")
    api_home_team_id = _positive_int(official_match["api_home_team_id"], "API home team ID")
    api_away_team_id = _positive_int(official_match["api_away_team_id"], "API away team ID")
    if home_team_id == away_team_id or api_home_team_id == api_away_team_id:
        raise ValueError("home and away team identities must be distinct")
    if official_match["fixture_link_status"] != "linked":
        raise ValueError("API fixture must have a unique linked official match")
    if not callable(resolve_player_id):
        raise ValueError("verified player identity resolver is required")
    if (
        not isinstance(acquired_at, datetime)
        or acquired_at.tzinfo is None
        or acquired_at.utcoffset() is None
    ):
        raise ValueError("acquisition timestamp must include a timezone")

    if not isinstance(fixture_summary, dict):
        raise ValueError("fixture summary must be an object")
    fixture = fixture_summary.get("fixture")
    teams = fixture_summary.get("teams")
    if not isinstance(fixture, dict) or not isinstance(teams, dict):
        raise ValueError("fixture summary requires fixture and teams objects")
    if _positive_int(fixture.get("id"), "response fixture ID") != fixture_id:
        raise ValueError("fixture summary does not match the linked API fixture")
    if not {"home", "away"} <= teams.keys():
        raise ValueError("fixture summary requires home and away teams")
    home = teams.get("home")
    away = teams.get("away")
    if not isinstance(home, dict) or not isinstance(away, dict):
        raise ValueError("fixture summary home and away must be objects")
    if (
        _positive_int(home.get("id"), "response home team ID") != api_home_team_id
        or _positive_int(away.get("id"), "response away team ID") != api_away_team_id
    ):
        raise ValueError("fixture home/away teams do not match the linked official match")
    status, duration_bound = _duration_bound(fixture.get("status", {}))

    if not isinstance(fixture_players, list) or len(fixture_players) != 2:
        raise ValueError("fixture player response requires both team groups")
    team_payloads: dict[int, dict[str, Any]] = {}
    for group in fixture_players:
        if not isinstance(group, dict):
            raise ValueError("fixture player team group must be an object")
        group_team = group.get("team")
        players = group.get("players")
        if not isinstance(group_team, dict) or not isinstance(players, list) or len(players) > 64:
            raise ValueError("fixture player team group is malformed or exceeds its player bound")
        source_team_id = _positive_int(group_team.get("id"), "fixture player team ID")
        if source_team_id in team_payloads:
            raise ValueError("fixture player response contains a duplicate team")
        team_payloads[source_team_id] = group
    if set(team_payloads) != {api_home_team_id, api_away_team_id}:
        raise ValueError("fixture player response teams do not match the fixture summary")

    outgoing, incoming = _substitution_minutes(
        substitution_events, api_home_team_id, api_away_team_id, duration_bound
    )
    normalized_teams: list[dict[str, Any]] = []
    all_reported_minutes: dict[tuple[int, int], int | None] = {}
    seen_fixture_player_ids: set[int] = set()
    seen_canonical_player_ids: set[int] = set()
    for side, official_team_id, source_team_id in (
        ("home", home_team_id, api_home_team_id),
        ("away", away_team_id, api_away_team_id),
    ):
        group_players = team_payloads[source_team_id]["players"]
        seen_source_ids: set[int] = set()
        resolved_players: list[dict[str, Any]] = []
        unresolved_ids: list[str] = []
        missing_minutes_count = 0
        for row in group_players:
            if not isinstance(row, dict) or not isinstance(row.get("player"), dict):
                raise ValueError("fixture player row requires a player object")
            source_player_id = _positive_int(row["player"].get("id"), "source player ID")
            if source_player_id in seen_source_ids or source_player_id in seen_fixture_player_ids:
                raise ValueError("fixture player response contains a duplicate source player")
            seen_source_ids.add(source_player_id)
            seen_fixture_player_ids.add(source_player_id)
            source_key = str(source_player_id)
            minutes = _minutes(row, duration_bound)
            all_reported_minutes[(source_team_id, source_player_id)] = minutes
            if minutes is None:
                missing_minutes_count += 1
            canonical_player_id = resolve_player_id(source_key)
            if canonical_player_id is None:
                unresolved_ids.append(source_key)
                continue
            canonical_player_id = _positive_int(canonical_player_id, "canonical player ID")
            if canonical_player_id in seen_canonical_player_ids:
                raise ValueError(
                    "verified player identity maps multiple fixture players to one player"
                )
            seen_canonical_player_ids.add(canonical_player_id)
            if minutes is None:
                continue
            resolved_players.append(
                {
                    "source_player_id": source_key,
                    "player_id": canonical_player_id,
                    "minutes": minutes,
                    "source_reported": True,
                    "derivation": "direct_source_field",
                }
            )
        normalized_teams.append(
            {
                "side": side,
                "team_id": official_team_id,
                "api_team_id": source_team_id,
                "players": sorted(resolved_players, key=lambda item: item["source_player_id"]),
                "source_reported_player_count": len(group_players),
                "missing_minutes_count": missing_minutes_count,
                "unresolved_player_count": len(unresolved_ids),
                "unresolved_source_player_ids": sorted(unresolved_ids),
            }
        )

    _check_substitution_consistency(all_reported_minutes, outgoing, incoming, duration_bound)
    source_hash = _canonical_response_hash(fixture_summary, fixture_players, substitution_events)
    return {
        "match_id": match_id,
        "api_fixture_id": fixture_id,
        "fixture_link_status": "linked",
        "match_status": status,
        "duration_bound_minutes": duration_bound,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "source_response_sha256": source_hash,
        "acquired_at": acquired_at.astimezone(UTC).isoformat(),
        "teams": normalized_teams,
    }
