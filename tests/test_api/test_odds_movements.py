from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from apps.backend.src.services.odds_market_reference import read_market_reference


def test_market_reference_binds_company_ids_as_text_and_maps_all_requested_brands():
    with patch("apps.backend.src.services.odds_market_reference.get_db") as get_db:
        cursor = (
            get_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        )
        source_quotes = [
            (2, "1x2d"),
            (545, "1x2d"),
            (12, "vip"),
            (80, "1x2d"),
            (82, "1x2d"),
            (115, "1x2d"),
            (177, "1x2d"),
            (281, "1x2d"),
        ]
        cursor.fetchall.return_value = [
            (
                101,
                {
                    "company_id": company_id,
                    "source": source,
                    "initial_home": 2.1,
                    "initial_line": 3.2,
                    "initial_away": 3.4,
                    "live_home": 2.0,
                    "live_line": 3.3,
                    "live_away": 3.6,
                },
            )
            for company_id, source in source_quotes
        ]

        references = read_market_reference([101])

    params = cursor.execute.call_args_list[1].args[1]
    assert params[0] == [101]
    assert params[1]
    assert all(isinstance(company_id, str) for company_id in params[1])
    assert set(params[1]) >= {str(company_id) for company_id, _ in source_quotes}
    assert references == {
        101: {
            "betfair": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "crown": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "ysb": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "macau": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "ladbrokes": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "william_hill": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "pinnacle": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
            "bet365": {"opening": [2.1, 3.2, 3.4], "latest": [2.0, 3.3, 3.6]},
        }
    }


def test_current_odds_movements_return_saved_quotes_during_official_rest_time(client):
    closed_window = MagicMock(is_open=False)
    closed_window.as_dict.return_value = {
        "is_open": False,
        "message": "官方竞彩休市中，今日 11:00 恢复开售",
    }
    with (
        patch(
            "apps.backend.src.services.odds_movement.get_sporttery_sales_window",
            return_value=closed_window,
        ),
        patch("apps.backend.src.services.odds_movement.get_db") as get_db,
    ):
        cursor = (
            get_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        )
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
                datetime(2026, 7, 13, 21, 30),
                "h",
                "主胜",
                Decimal("2.1000"),
                None,
                Decimal("0.476190"),
                None,
                "complete",
                "opening",
                None,
            )
        ]
        response = client.get(
            "/api/dashboard/odds/movements?scope=current&play_type=spf&resolution=raw"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["sales_window"] == closed_window.as_dict.return_value
    assert payload["matches"][0]["series"][0]["sp_value"] == 2.1
    assert payload["matches"][0]["series"][0]["snapshot_time"] == "2026-07-13T21:30:00+08:00"
    cursor.execute.assert_called_once()
    sql = cursor.execute.call_args.args[0]
    assert "LOWER(m.match_status) IN ('scheduled', 'selling', 'not_started')" in sql
    assert "official_odds_snapshots available_odds" in sql
    assert "market.is_open = TRUE" not in sql


def test_batch_odds_movements_returns_all_current_matches_in_one_query(client):
    open_window = MagicMock(is_open=True)
    open_window.as_dict.return_value = {"is_open": True}
    with (
        patch(
            "apps.backend.src.services.odds_movement.get_sporttery_sales_window",
            return_value=open_window,
        ),
        patch("apps.backend.src.services.odds_movement.get_db") as get_db,
    ):
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
    assert "_collector_timezone" in sql
    assert "getFixedBonusV1.qry" in sql
    assert "snapshot.snapshot_time + INTERVAL '8 hours'" in sql
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
    assert "date_trunc('hour', snapshot.business_snapshot_time)" in sql
    assert cursor.execute.call_args.args[1]["business_date"] == "2026-07-13"
