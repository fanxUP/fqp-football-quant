from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scripts.official_odds_capture import (
    OfficialCaptureCandidate,
    _close_expired_sales,
    collect_due_official_odds,
)


def test_expired_sales_close_after_final_capture_grace(mock_conn):
    conn, cur = mock_conn
    now = datetime(2026, 7, 15, 11, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    _close_expired_sales(conn, now)

    query, params = cur.execute.call_args.args
    assert "sale_status = 'closed'" in query
    assert "kickoff_time < %s" in query
    assert params[0] == datetime(2026, 7, 15, 11, 20)
    conn.commit.assert_called_once()


def test_no_due_matches_still_refreshes_odds_source_health():
    now = datetime(2026, 7, 15, 11, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    connection = MagicMock()

    with (
        patch("scripts.official_odds_capture.get_db") as get_db,
        patch("scripts.official_odds_capture._load_candidates", return_value=[]),
        patch("scripts.official_odds_capture._close_expired_sales"),
        patch("scripts.official_odds_capture.update_health") as update_health,
    ):
        get_db.return_value.__enter__.return_value = connection

        result = collect_due_official_odds(now)

    assert result == {"status": "ok", "matches_due": 0, "snapshots_inserted": 0}
    update_health.assert_called_once_with(connection, "sporttery", "odds", "ok", 0)


def test_due_collector_fetches_once_and_records_complete_offered_play():
    now = datetime(2026, 7, 14, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    candidate = OfficialCaptureCandidate(
        match_id=12,
        business_date=date(2026, 7, 14),
        official_match_code="周二201",
        kickoff_time=datetime(2026, 7, 14, 19, 15),
        expected_play_types=("spf",),
        last_attempt_at=None,
        last_attempt_status=None,
        final_attempted=False,
    )
    source_match = {
        "official_match_code": "周二201",
        "business_date": "2026-07-14",
        "raw_json": {"matchNumStr": "周二201"},
        "_markets": [{"play_type": "spf", "is_open": True}],
    }
    snapshots = [
        {"play_type": "spf", "option_code": code, "option_name": name, "sp_value": 2.0}
        for code, name in (("h", "主胜"), ("d", "平"), ("a", "客胜"))
    ]
    client = MagicMock()
    client.get_uniform_match_calculator.return_value = {"value": {}}
    connection = MagicMock()

    with (
        patch("scripts.official_odds_capture.get_db") as get_db,
        patch("scripts.official_odds_capture._load_candidates", return_value=[candidate]),
        patch("scripts.official_odds_capture._close_expired_sales"),
        patch("scripts.official_odds_capture._reserve_batch", return_value=99),
        patch("scripts.official_odds_capture.SportteryClient", return_value=client),
        patch(
            "scripts.official_odds_capture.parse_matches_from_response", return_value=[source_match]
        ),
        patch(
            "scripts.official_odds_capture.parse_odds_snapshots_from_match", return_value=snapshots
        ),
        patch("scripts.official_odds_capture.store_markets"),
        patch(
            "scripts.official_odds_capture.store_odds_snapshots",
            return_value={"inserted": 3, "errors": []},
        ) as store_odds,
        patch("scripts.official_odds_capture._finish_batch") as finish_batch,
        patch("scripts.official_odds_capture.log_crawl"),
        patch("scripts.official_odds_capture.update_health") as update_health,
    ):
        get_db.return_value.__enter__.return_value = connection

        result = collect_due_official_odds(now)

    assert result == {
        "status": "ok",
        "matches_due": 1,
        "matches_complete": 1,
        "snapshots_inserted": 3,
    }
    client.get_uniform_match_calculator.assert_called_once_with()
    store_odds.assert_called_once()
    stored_snapshots = store_odds.call_args.kwargs["snapshots"]
    assert all(
        snapshot["raw_json"]["_collector_timezone"] == "Asia/Shanghai"
        for snapshot in stored_snapshots
    )
    finish_batch.assert_called_once_with(connection, 99, "complete", ("spf",), 3, None)
    update_health.assert_called_once_with(connection, "sporttery", "odds", "ok", 0)
