from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest

from scripts.api_football_client import ApiFootballClient
from scripts.player_appearance_facts import build_actual_appearance_facts

ACQUIRED_AT = datetime(2026, 11, 10, 9, 30, tzinfo=UTC)
OFFICIAL_MATCH = {
    "match_id": 55,
    "api_fixture_id": 900,
    "fixture_link_status": "linked",
    "home_team_id": 11,
    "away_team_id": 12,
    "api_home_team_id": 10,
    "api_away_team_id": 20,
}


def fixture(*, fixture_id=900, status="FT", elapsed=90, extra=None, home=10, away=20):
    return {
        "fixture": {
            "id": fixture_id,
            "status": {"short": status, "elapsed": elapsed, "extra": extra},
        },
        "teams": {"home": {"id": home}, "away": {"id": away}},
    }


def player(source_id, minutes="missing", name="Alex Same"):
    games = {} if minutes == "missing" else {"minutes": minutes}
    return {"player": {"id": source_id, "name": name}, "statistics": [{"games": games}]}


def response(*, home=None, away=None):
    home_players = [player(101, 90)] if home is None else home
    away_players = [player(201, 90)] if away is None else away
    return [
        {"team": {"id": 10}, "players": home_players},
        {"team": {"id": 20}, "players": away_players},
    ]


def build(*, official=None, summary=None, payload=None, resolve=None, events=None, acquired=None):
    mappings = {"101": 1001, "102": 1002, "103": 1003, "104": 1004, "201": 2001}
    return build_actual_appearance_facts(
        official_match=official or OFFICIAL_MATCH,
        fixture_summary=summary or fixture(),
        fixture_players=payload if payload is not None else response(),
        resolve_player_id=resolve or mappings.get,
        acquired_at=acquired or ACQUIRED_AT,
        substitution_events=events,
    )


def test_direct_minutes_zero_and_missing_are_distinct_and_names_do_not_resolve():
    payload = response(
        home=[
            player(101, 90),
            player(102, 0),
            player(103, None),
            player(104),
            player(999, 77, name="Alex Same"),
        ]
    )
    facts = build(payload=payload, resolve={"101": 1001, "102": 1002, "103": 1003, "104": 1004}.get)

    home = facts["teams"][0]
    assert [
        (row["source_player_id"], row["player_id"], row["minutes"]) for row in home["players"]
    ] == [
        ("101", 1001, 90),
        ("102", 1002, 0),
    ]
    assert home["source_reported_player_count"] == 5
    assert home["missing_minutes_count"] == 2
    assert home["unresolved_player_count"] == 1
    assert home["unresolved_source_player_ids"] == ["999"]


def test_verified_source_ids_keep_same_named_players_separate():
    payload = response(
        home=[player(101, 90, name="Alex Same")],
        away=[player(201, 90, name="Alex Same")],
    )
    facts = build(payload=payload, resolve={"101": 1001, "201": 2001}.get)

    assert facts["teams"][0]["players"][0]["player_id"] == 1001
    assert facts["teams"][1]["players"][0]["player_id"] == 2001


def test_unresolved_players_with_missing_minutes_count_both_coverage_gaps():
    facts = build(payload=response(home=[player(999, None)]), resolve={}.get)

    home = facts["teams"][0]
    assert home["players"] == []
    assert home["missing_minutes_count"] == 1
    assert home["unresolved_player_count"] == 1
    assert home["unresolved_source_player_ids"] == ["999"]


def test_duplicate_team_group_or_cross_team_source_player_is_rejected():
    duplicate_group = {"team": {"id": 10}, "players": [player(101, 90)]}
    with pytest.raises(ValueError, match="duplicate team"):
        build(payload=[duplicate_group, duplicate_group])

    with pytest.raises(ValueError, match="duplicate source player"):
        build(payload=response(home=[player(101, 90)], away=[player(101, 90)]))


@pytest.mark.parametrize("status", ["NS", "1H", "HT", "2H", "ET", "P", "CANC", "ABD"])
def test_unfinished_or_unsupported_fixture_status_is_rejected(status):
    with pytest.raises(ValueError, match="finished"):
        build(summary=fixture(status=status))


@pytest.mark.parametrize(
    "changes",
    [
        {"official": {**OFFICIAL_MATCH, "fixture_link_status": "pending"}},
        {"official": {**OFFICIAL_MATCH, "api_fixture_id": 901}},
        {"summary": fixture(fixture_id=901)},
        {"summary": fixture(home=20, away=10)},
    ],
)
def test_fixture_must_be_uniquely_linked_and_home_away_must_match(changes):
    with pytest.raises(ValueError):
        build(**changes)


@pytest.mark.parametrize("minutes", [True, "90", -1, 91])
def test_noninteger_negative_or_over_duration_minutes_are_rejected(minutes):
    with pytest.raises(ValueError, match="minutes"):
        build(payload=response(home=[player(101, minutes)]))


def test_extra_time_minutes_are_bounded_by_finished_match_duration():
    aet = fixture(status="AET", elapsed=120, extra=0)
    facts = build(summary=aet, payload=response(home=[player(101, 120)]))
    assert facts["duration_bound_minutes"] == 120
    assert facts["teams"][0]["players"][0]["minutes"] == 120

    with pytest.raises(ValueError, match="minutes"):
        build(summary=aet, payload=response(home=[player(101, 121)]))


@pytest.mark.parametrize(
    ("status", "elapsed"),
    [("FT", 106), ("AET", 136), ("PEN", 136)],
)
def test_implausible_finished_duration_is_rejected(status, elapsed):
    with pytest.raises(ValueError, match="elapsed time"):
        build(summary=fixture(status=status, elapsed=elapsed))


def test_substitution_events_only_reject_conflicts_and_never_estimate_minutes():
    events = [
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 60, "extra": None},
            "player": {"id": 101},
            "assist": {"id": 102},
        }
    ]
    with pytest.raises(ValueError, match="substitution"):
        build(payload=response(home=[player(101, 90), player(102, 0)]), events=events)

    facts = build(payload=response(home=[player(101, 60), player(102, 30)]), events=events)
    assert {row["source_player_id"]: row["minutes"] for row in facts["teams"][0]["players"]} == {
        "101": 60,
        "102": 30,
    }


def test_incoming_substitution_cannot_report_more_minutes_than_remaining():
    events = [
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 80, "extra": None},
            "player": {"id": 101},
            "assist": {"id": 102},
        }
    ]
    with pytest.raises(ValueError, match="substitution"):
        build(payload=response(home=[player(102, 20)]), events=events)


@pytest.mark.parametrize("reported_minutes", [10, 59])
def test_known_substitution_interval_rejects_impossible_minutes(reported_minutes):
    events = [
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 20, "extra": None},
            "player": {"id": 103},
            "assist": {"id": 102},
        },
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 60, "extra": None},
            "player": {"id": 102},
            "assist": {"id": 104},
        },
    ]
    with pytest.raises(ValueError, match="known substitution interval"):
        build(payload=response(home=[player(102, reported_minutes)]), events=events)


@pytest.mark.parametrize("reported_minutes", [38, 42])
def test_known_substitution_interval_accepts_two_minute_rounding_boundary(reported_minutes):
    events = [
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 20, "extra": None},
            "player": {"id": 103},
            "assist": {"id": 102},
        },
        {
            "type": "subst",
            "team": {"id": 10},
            "time": {"elapsed": 60, "extra": None},
            "player": {"id": 102},
            "assist": {"id": 104},
        },
    ]
    facts = build(payload=response(home=[player(102, reported_minutes)]), events=events)
    assert facts["teams"][0]["players"][0]["minutes"] == reported_minutes


def test_same_verified_canonical_player_cannot_appear_for_both_teams():
    with pytest.raises(ValueError, match="maps multiple fixture players"):
        build(
            payload=response(home=[player(101, 90)], away=[player(201, 90)]), resolve=lambda _: 1001
        )


def test_response_hash_is_deterministic_and_tracks_source_changes():
    payload = response()
    first = build(payload=payload)
    reordered = deepcopy(payload)
    reordered[0]["players"][0]["statistics"][0]["games"] = {"minutes": 90}
    second = build(payload=reordered)
    changed = build(payload=response(home=[player(101, 89)]))

    assert first["source_response_sha256"] == second["source_response_sha256"]
    assert first["source_response_sha256"] != changed["source_response_sha256"]
    assert len(first["source_response_sha256"]) == 64


def test_acquisition_time_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone"):
        build(acquired=datetime(2026, 11, 10, 9, 30))


def test_titan_default90_rows_are_not_api_fixture_player_payloads():
    titan_row = [{"player_id": 101, "starter": 1, "minutes": 90, "reported_minutes": False}]
    with pytest.raises(ValueError):
        build(payload=titan_row)


def test_fixture_players_client_uses_explicit_fixture_parameter_without_network():
    from unittest.mock import patch

    payload = {
        "response": [{"team": {"id": 10}, "players": []}],
        "results": 1,
        "paging": {"current": 1, "total": 1},
    }
    client = ApiFootballClient(api_key="test-key")
    try:
        with patch.object(client, "_request", return_value=payload) as request:
            assert client.get_fixture_players(900) == payload["response"]
        request.assert_called_once_with("fixtures/players", params={"fixture": 900})
    finally:
        client.close()


@pytest.mark.parametrize("fixture_id", [0, -1, True, "900", None])
def test_fixture_players_client_requires_a_positive_integer_id(fixture_id):
    from unittest.mock import patch

    client = ApiFootballClient(api_key="test-key")
    try:
        with patch.object(client, "_request") as request, pytest.raises(ValueError):
            client.get_fixture_players(fixture_id)
        request.assert_not_called()
    finally:
        client.close()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"response": None},
        {"response": {}},
        {"response": [None]},
        {"response": [{"team": {"id": 10}, "players": "invalid"}]},
        {"response": [], "results": 1},
        {"response": [{"team": {"id": 10}, "players": []}], "results": False},
        {"response": [], "paging": {"current": 1, "total": 2}},
        {"response": [], "paging": {"current": 2, "total": 2}},
        {"response": [], "paging": {"current": True, "total": 1}},
    ],
)
def test_fixture_players_client_rejects_malformed_or_partial_payload(payload):
    from unittest.mock import patch

    from scripts.request_transport import ProviderRequestError

    client = ApiFootballClient(api_key="test-key")
    try:
        with patch.object(client, "_request", return_value=payload):
            with pytest.raises(ProviderRequestError):
                client.get_fixture_players(900)
    finally:
        client.close()
