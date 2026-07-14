from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch


def test_batch_odds_movements_returns_all_current_matches_in_one_query(client):
    with patch("apps.backend.src.services.odds_movement.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                101,
                7,
                "周二201",
                date(2026, 7, 14),
                "测试联赛",
                "主队",
                "客队",
                datetime(2026, 7, 14, 19, 15),
                datetime(2026, 7, 14, 17, 30),
                "h",
                "主胜",
                Decimal("2.1000"),
                None,
                Decimal("0.476190"),
                None,
                "complete",
                "opening",
                None,
            ),
            (
                None,
                8,
                "周二202",
                date(2026, 7, 14),
                "测试联赛",
                "甲队",
                "乙队",
                datetime(2026, 7, 14, 20, 0),
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            ),
        ]

        response = client.get(
            "/api/dashboard/odds/movements?scope=current&play_type=spf&resolution=raw"
        )

    assert response.status_code == 200
    assert cursor.execute.call_count == 1
    sql = cursor.execute.call_args.args[0]
    assert "LEFT JOIN selected_snapshots" in sql
    assert "timezone('Asia/Shanghai', NOW())" in sql
    payload = response.json()
    assert payload["total"] == 2
    assert payload["matches"][0]["series"][0]["sp_value"] == 2.1
    assert payload["matches"][0]["kickoff_time"].endswith("+08:00")
    assert payload["matches"][1]["series"] == []


def test_historical_odds_movements_requires_date_and_supports_hourly_resolution(client):
    missing_date = client.get(
        "/api/dashboard/odds/movements?scope=history&play_type=spf&resolution=hour"
    )
    assert missing_date.status_code == 422

    with patch("apps.backend.src.services.odds_movement.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        response = client.get(
            "/api/dashboard/odds/movements?scope=history&business_date=2026-07-13"
            "&play_type=bf&resolution=hour"
        )

    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    assert "DISTINCT ON" in sql
    assert "date_trunc('hour', snapshot.snapshot_time)" in sql
    assert cursor.execute.call_args.args[1]["business_date"] == "2026-07-13"
