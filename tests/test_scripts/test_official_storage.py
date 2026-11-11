from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

import scripts.official_storage as official_storage
from scripts.data_contracts import FactStatus
from scripts.official_storage import (
    store_match_sale_stop_time,
    store_matches,
    store_pool_issue_matches,
    store_results,
)


def test_absent_cutoff_fields_never_trigger_an_unbound_fixture_update():
    conn = MagicMock()
    for match in ({}, {"_sale_stop_time_present": False}, {"_sale_stop_time_present": True}):
        assert store_match_sale_stop_time(conn, 7, match) == 0
    conn.cursor.assert_not_called()


def test_store_matches_rejects_rows_without_canonical_official_identity():
    conn = MagicMock()

    result = store_matches(
        conn,
        [
            {
                "business_date": "2026-07-13",
                "official_match_code": "",
                "source_match_id": None,
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2026-07-13T20:00:00",
            }
        ],
    )

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["errors"] == [
        {
            "match_code": "",
            "error": "missing or invalid Sporttery match code",
        }
    ]
    conn.cursor.assert_not_called()


def test_store_matches_rejects_rows_without_official_match_id():
    conn = MagicMock()

    result = store_matches(
        conn,
        [
            {
                "business_date": "2026-07-13",
                "official_match_code": "周日001",
                "source_match_id": None,
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2026-07-13T20:00:00",
            }
        ],
    )

    assert result["errors"] == [
        {
            "match_code": "周日001",
            "error": "missing Sporttery matchId",
        }
    ]
    conn.cursor.assert_not_called()


def test_store_matches_rejects_numbered_match_outside_selected_event_season():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("世界杯", "2026-06-11", "2026-07-20"),
    ]

    result = store_matches(
        conn,
        [
            {
                "business_date": "2022-11-20",
                "official_match_code": "周日001",
                "source_match_id": "10001",
                "league_name": "世界杯",
                "home_team_name": "A",
                "away_team_name": "B",
                "kickoff_time": "2022-11-20T20:00:00",
            }
        ],
    )

    assert result["inserted"] == 0
    assert result["updated"] == 0
    assert result["errors"] == [
        {
            "match_code": "周日001",
            "error": "outside retained event seasons",
        }
    ]
    assert cursor.execute.call_count == 1


def test_confirmed_result_closes_match_sales_even_when_match_was_already_settled():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (9, True)

    result = store_results(
        conn,
        [
            {
                "match_id": 7,
                "result_status": "confirmed",
                "full_home_goals": 2,
                "full_away_goals": 1,
            }
        ],
    )

    close_query = cursor.execute.call_args_list[-1].args[0]
    assert "sale_status = 'closed'" in close_query
    assert "sale_status IS DISTINCT FROM 'closed'" in close_query
    assert result["settled"] == 1


def test_store_matches_accepts_each_retained_season_without_filling_the_gap():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("联赛", "2021-08-01", "2022-05-31"),
        ("联赛", "2025-08-01", "2026-05-31"),
    ]
    cursor.fetchone.return_value = (7, True)
    matches = [
        dict(
            business_date=day,
            official_match_code=f"周日{n:03d}",
            source_match_id=str(n),
            league_name="联赛",
            home_team_name="A",
            away_team_name="B",
            kickoff_time=day + "T23:00:00",
        )
        for n, day in enumerate(["2022-05-31", "2023-01-01", "2025-08-01"], 1)
    ]
    result = store_matches(conn, matches)
    assert result["inserted"] == 2
    assert [error["match_code"] for error in result["errors"]] == ["周日002"]
    assert "FROM official_event_season_retention" in cursor.execute.call_args_list[0].args[0]


def test_pool_match_storage_uses_shared_identity_and_caller_transaction(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = ("t14c", "26001", "t14c")
    resolved = MagicMock(
        return_value=dict(
            fixture_id=81, official_match_id=7, identity_status="linked", evidence={"fixture": True}
        )
    )
    monkeypatch.setattr("scripts.official_storage.resolve_pool_fixture", resolved)

    inserted = store_pool_issue_matches(
        conn,
        517,
        [
            {
                "match_order": 1,
                "home_team_name": "萨巴赫",
                "away_team_name": "库奥皮奥",
                "kickoff_time": "2026-07-21T16:00:00Z",
                "league_name": "欧冠",
            }
        ],
    )

    assert inserted == 1
    query = " ".join(cursor.execute.call_args.args[0].split())
    params = cursor.execute.call_args.args[1]
    resolved.assert_called_once()
    assert resolved.call_args.kwargs == {
        "game_type": "t14c",
        "issue_no": "26001",
        "source_game_type": "t14c",
    }
    assert query.count("%s") == len(params)
    assert params[2] == 7
    assert params[7].isoformat() == "2026-07-22T00:00:00"
    assert params[26:28] == (81, "linked")
    conn.commit.assert_not_called()


def test_live_result_capture_appends_point_in_time_source_evidence(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (71, True)
    captured = []
    visibility_receipts = []
    monkeypatch.setattr(
        official_storage,
        "append_observation",
        lambda connection, **kwargs: captured.append((connection, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        official_storage,
        "capture_observation_cutoff",
        lambda connection, *, streams: visibility_receipts.append((connection, streams)),
    )
    acquired = datetime(2026, 11, 11, 1, 0, tzinfo=UTC)
    published_local = datetime(2026, 11, 10, 20, 30)

    result = official_storage.store_results(
        conn,
        [
            {
                "match_id": 7,
                "result_status": "confirmed",
                "full_home_goals": 2,
                "full_away_goals": 1,
                "official_publish_time": published_local,
                "raw_json": {"matchId": "sporttery-7", "payload": "official"},
            }
        ],
        source_acquired_at=acquired,
    )

    assert result["inserted"] == 1
    assert result["errors"] == []
    assert len(captured) == 1
    connection, evidence = captured[0]
    assert connection is conn
    assert evidence["source_id"] == "sporttery"
    assert evidence["domain"] == "results"
    assert evidence["subject_key"] == "full_time_score"
    assert evidence["fact_status"] == FactStatus.VALUE
    assert evidence["value"] == {
        "away_goals": 1,
        "home_goals": 2,
        "result_status": "confirmed",
    }
    assert evidence["acquired_at"] == evidence["verified_at"] == acquired
    assert evidence["published_at"] == published_local.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    assert visibility_receipts == [
        (
            conn,
            [
                {
                    "match_id": 7,
                    "source_id": "sporttery",
                    "domain": "results",
                    "subject_key": "full_time_score",
                }
            ],
        )
    ]
    upsert = next(
        call.args[0]
        for call in cursor.execute.call_args_list
        if "INSERT INTO official_results" in call.args[0]
    )
    assert "official_publish_time = COALESCE( EXCLUDED.official_publish_time" in " ".join(
        upsert.split()
    )
    assert conn.commit.call_count == 2


def test_historical_store_without_capture_time_does_not_claim_live_observation(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (71, True)
    captured = []
    monkeypatch.setattr(
        official_storage,
        "append_observation",
        lambda connection, **kwargs: captured.append(kwargs),
        raising=False,
    )

    result = official_storage.store_results(
        conn,
        [
            {
                "match_id": 7,
                "result_status": "confirmed",
                "full_home_goals": 2,
                "full_away_goals": 1,
            }
        ],
    )

    assert result["errors"] == []
    assert captured == []


def test_live_result_visibility_receipt_failure_fails_closed_after_result_commit(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (71, True)
    monkeypatch.setattr(official_storage, "append_observation", lambda *_args, **_kwargs: None)

    def fail_receipt(*_args, **_kwargs):
        raise RuntimeError("cutoff store unavailable")

    monkeypatch.setattr(official_storage, "capture_observation_cutoff", fail_receipt)

    with pytest.raises(RuntimeError, match="visibility receipt could not be persisted"):
        official_storage.store_results(
            conn,
            [
                {
                    "match_id": 7,
                    "result_status": "confirmed",
                    "full_home_goals": 2,
                    "full_away_goals": 1,
                    "raw_json": {"matchId": "sporttery-7"},
                }
            ],
            source_acquired_at=datetime(2026, 11, 11, 1, 0, tzinfo=UTC),
        )

    assert conn.commit.call_count == 1
    conn.rollback.assert_called_once_with()


def test_unconfirmed_and_invalid_result_timestamps_are_not_promoted_to_labels():
    assert official_storage._result_observation(
        {"result_status": "pending", "full_home_goals": 2, "full_away_goals": 1}
    ) == (FactStatus.UNKNOWN, None)
    assert official_storage._result_observation(
        {"result_status": "void", "full_home_goals": 2, "full_away_goals": 1}
    ) == (FactStatus.NOT_APPLICABLE, None)
    assert official_storage._official_result_published_at("not-a-time") == (None, "invalid")


def test_p104_capture_failure_rolls_back_result_upsert_and_does_not_settle_match(monkeypatch):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (71, True)

    def fail_observation(*_args, **_kwargs):
        raise RuntimeError("observation unavailable")

    monkeypatch.setattr(official_storage, "append_observation", fail_observation)

    result = official_storage.store_results(
        conn,
        [
            {
                "match_id": 7,
                "result_status": "confirmed",
                "full_home_goals": 2,
                "full_away_goals": 1,
                "raw_json": {"matchId": "sporttery-7"},
            }
        ],
        source_acquired_at=datetime(2026, 11, 11, 1, 0, tzinfo=UTC),
    )

    assert result["inserted"] == 0
    assert result["settled"] == 0
    assert result["errors"] == [{"match_id": 7, "error": "observation unavailable"}]
    statements = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
    assert "ROLLBACK TO SAVEPOINT official_result_0" in statements
    assert not any(statement.startswith("UPDATE official_matches") for statement in statements)
