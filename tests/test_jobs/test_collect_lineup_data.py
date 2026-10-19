from unittest.mock import MagicMock, patch

import pytest

from scripts.api_football_player import get_or_create_player
from scripts.jobs.collect_lineup_data import _process_lineup


def source_lineup():
    return {
        "formation": "4-3-3",
        "startXI": [{"player": {"id": i, "name": f"Starter{i}", "pos": "G"}} for i in range(1, 12)],
        "substitutes": [],
    }


def test_api_fixture_lineup_is_stored_as_confirmed_in_one_commit():
    conn = MagicMock()
    with (
        patch(
            "scripts.jobs.collect_lineup_data._get_or_create_player", side_effect=range(101, 112)
        ),
        patch(
            "scripts.jobs.collect_lineup_data.store_lineup_observation", return_value=501
        ) as store,
    ):
        result = _process_lineup(
            conn, 7, source_lineup(), 11, "2026-07-19T04:30:00", api_fixture_id=900
        )
    assert result == 501
    assert store.call_args.args[1]["lineup_type"] == "confirmed"
    assert len(store.call_args.args[2]) == 11
    assert store.call_args.kwargs["api_fixture_id"] == 900
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


def test_group_failure_is_rolled_back_and_not_committed():
    conn = MagicMock()
    with patch(
        "scripts.jobs.collect_lineup_data._get_or_create_player", side_effect=RuntimeError("fixed")
    ):
        with pytest.raises(RuntimeError, match="fixed"):
            _process_lineup(conn, 7, source_lineup(), 11, "2026-07-19T04:30:00", api_fixture_id=900)
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


@pytest.mark.parametrize("source_id", [None, False, 0, -1, "123"])
def test_invalid_player_identity_never_reaches_database(source_id):
    conn = MagicMock()
    with pytest.raises(ValueError, match="source ID"):
        get_or_create_player(conn, dict(id=source_id), prefer_short_position=True, commit=False)
    conn.cursor.assert_not_called()


def test_player_creation_can_join_caller_transaction():
    conn = MagicMock()
    with (
        patch("scripts.api_football_player.get_player_by_code", return_value=None),
        patch("scripts.api_football_player.store_player", return_value=10) as store,
    ):
        assert (
            get_or_create_player(
                conn, dict(id=1, name="P1"), prefer_short_position=True, commit=False
            )
            == 10
        )
    assert store.call_args.kwargs["commit"] is False


@pytest.mark.parametrize(
    "mode", ["recent", "unpublished", "wrong_fixture", "quota", "unknown_team", "dry"]
)
def test_lineup_job_response_paths_use_receipts_and_respect_recent_checks(monkeypatch, mode):
    from datetime import datetime

    from scripts.api_football_client import ApiFootballRateLimitError
    from scripts.jobs import collect_lineup_data as job

    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    match = dict(id=7, home_team_id=11, away_team_id=12, kickoff_time=datetime(2026, 10, 20, 20))
    conn = MagicMock()
    client = MagicMock(last_response_meta={"errors": {}}, call_count_today=0)
    detail = dict(fixture=dict(id=901 if mode == "wrong_fixture" else 900), lineups=[])
    if mode == "unknown_team":
        detail["lineups"] = [dict(source_lineup(), team=dict(name="Unmapped"))]
    client.get_fixtures.side_effect = [
        [],
        ApiFootballRateLimitError("fixed") if mode == "quota" else [detail],
    ]
    with (
        patch.object(job, "get_db") as db,
        patch.object(job, "ApiFootballClient", return_value=client),
        patch.object(job, "load_supported_matches", return_value=[match]),
        patch.object(job, "load_api_aliases", return_value={"Home": 11, "Away": 12}),
        patch.object(job, "find_matching_fixture", return_value={"fixture": {"id": 900}}),
        patch.object(job, "_has_recent_lineup_checks", return_value=mode == "recent"),
        patch.object(job, "record_lineup_status") as status,
        patch.object(job, "record_failed_player_query", return_value=True) as failed,
    ):
        db.return_value.__enter__.return_value = conn
        result = job._run_impl(dry_run=mode == "dry")
    client.close.assert_called_once()
    if mode == "recent":
        client.get_fixtures.assert_not_called()
        assert result["matches_recently_checked"] == 1
        assert result["quality_status"] == "recently_checked"
        assert "未重新核实" in result["quality_note"]
    elif mode == "unpublished":
        assert status.call_count == 2 and result["quality_status"] == "waiting"
        failed.assert_not_called()
    elif mode == "dry":
        status.assert_not_called()
        failed.assert_not_called()
        conn.commit.assert_not_called()
    else:
        failed.assert_called_once()
        status.assert_not_called()
        assert result["quality_status"] == "degraded"


@pytest.mark.parametrize("has_recent", [True, False])
@pytest.mark.parametrize("outcome", ["waiting", "failed", "confirmed"])
def test_lineup_recent_receipts_do_not_mask_waiting_or_failed_matches(
    monkeypatch, has_recent, outcome
):
    from datetime import datetime

    from scripts.jobs import collect_lineup_data as job

    monkeypatch.setenv("API_FOOTBALL_KEY", "test-key")
    due = dict(id=8, home_team_id=11, away_team_id=12, kickoff_time=datetime(2026, 10, 20, 20))
    matches = [dict(due, id=7), due] if has_recent else [due]
    client = MagicMock(last_response_meta={"errors": {}}, call_count_today=0)
    client.get_fixtures.side_effect = [
        [],
        [
            dict(
                fixture=dict(id=900),
                lineups=[dict(source_lineup(), team=dict(name=name)) for name in ("Home", "Away")],
            )
        ],
    ]
    with (
        patch.object(job, "get_db"),
        patch.object(job, "ApiFootballClient", return_value=client),
        patch.object(job, "load_supported_matches", return_value=matches),
        patch.object(job, "load_api_aliases", return_value={"Home": 11, "Away": 12}),
        patch.object(job, "find_matching_fixture", return_value={"fixture": {"id": 900}}),
        patch.object(job, "_has_recent_lineup_checks", side_effect=lambda conn, m: m["id"] == 7),
        patch.object(job, "_process_lineup") as process,
        patch.object(job, "record_failed_player_query", return_value=True),
    ):
        if outcome == "failed":
            process.side_effect = RuntimeError("fixed")
        else:
            process.return_value = 101 if outcome == "confirmed" else None
        result = job._run_impl()
    expected = (
        "degraded"
        if outcome == "failed"
        else "waiting"
        if outcome == "waiting"
        else "recently_checked"
        if has_recent
        else "healthy"
    )
    assert result["quality_status"] == expected
    assert result["matches_recently_checked"] == int(has_recent)
    assert bool(result["quality_note"]) is has_recent
    assert client.get_fixtures.call_count == 2
    client.close.assert_called_once()
