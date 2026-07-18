from datetime import date
from unittest.mock import MagicMock, patch


def test_list_official_matches_reads_sporttery_id_from_raw_json(client):
    with patch("apps.backend.src.routers.official.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                1,
                "周五098",
                "世界杯",
                "西班牙",
                "比利时",
                "2026-07-11T03:00:00",
                "scheduled",
                "2040466",
            )
        ]

        response = client.get("/api/official/matches?date=2026-07-10")

    assert response.status_code == 200
    cursor.execute.assert_called_once()
    assert "business_date = %s::date" in cursor.execute.call_args.args[0]
    assert response.json()["matches"][0]["official_match_code"] == "周五098"
    assert response.json()["matches"][0]["sporttery_match_id"] == "2040466"


def test_list_collection_status_exposes_official_source_gaps(client):
    with patch("apps.backend.src.routers.official.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                3,
                "2026-07-01",
                "results",
                "sporttery",
                "blocked",
                "https://webapi.sporttery.cn/gateway/jc/football/getMatchResultV1.qry",
                None,
                None,
                0,
                0,
                0,
                "567 Restricted Access",
                "2026-07-11T12:00:00",
            )
        ]

        response = client.get(
            "/api/official/collection-status?business_date=2026-07-01&status=blocked"
        )

    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "official_collection_status" in sql
    assert params["business_date"] == "2026-07-01"
    assert params["status"] == "blocked"
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["source_name"] == "sporttery"
    assert payload["items"][0]["status"] == "blocked"
    assert "567" in payload["items"][0]["error_message"]


def test_list_odds_history_matches_returns_only_matches_with_official_snapshots(client):
    with patch("apps.backend.src.routers.official.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                304,
                "周一005",
                "英超",
                "曼彻斯特城",
                "利雅得新月",
                "2025-07-01T03:00:00",
                ["bf", "bqc", "spf", "zjq"],
            )
        ]

        response = client.get("/api/official/odds-history/matches?limit=20&search=曼城")

    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "official_odds_snapshots" in sql
    assert "EXISTS" in sql
    assert sql.index("LIMIT %(limit)s") < sql.index("ARRAY_AGG")
    assert params["search"] == "%曼城%"
    payload = response.json()
    assert payload["total"] == 1
    assert payload["matches"][0]["id"] == 304
    assert payload["matches"][0]["play_types"] == ["bf", "bqc", "spf", "zjq"]


def test_odds_index_separates_current_open_matches_from_historical_dates(client):
    open_window = MagicMock(is_open=True)
    open_window.as_dict.return_value = {"is_open": True}
    with (
        patch(
            "apps.backend.src.routers.official.get_sporttery_sales_window", return_value=open_window
        ),
        patch("apps.backend.src.routers.official.get_db") as get_db,
    ):
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("current", None, 4),
            ("history", date(2026, 7, 13), 6),
            ("history", date(2026, 7, 12), 8),
        ]

        response = client.get("/api/official/odds-index")

    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "timezone('Asia/Shanghai', NOW())" in sql
    assert "market.is_open = TRUE" in sql
    assert params["sales_open"] is True
    assert response.json() == {
        "current": {"count": 4},
        "history": [
            {"business_date": "2026-07-13", "match_count": 6},
            {"business_date": "2026-07-12", "match_count": 8},
        ],
        "sales_window": {"is_open": True},
    }


def test_odds_index_marks_current_scope_unavailable_during_official_rest_time(client):
    closed_window = MagicMock(is_open=False)
    closed_window.as_dict.return_value = {
        "is_open": False,
        "message": "官方竞彩休市中，今日 11:00 恢复开售",
    }
    with (
        patch(
            "apps.backend.src.routers.official.get_sporttery_sales_window",
            return_value=closed_window,
        ),
        patch("apps.backend.src.routers.official.get_db") as get_db,
    ):
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            ("current", None, 0),
            ("history", date(2026, 7, 13), 6),
        ]

        response = client.get("/api/official/odds-index")

    assert response.status_code == 200
    sql, params = cursor.execute.call_args.args
    assert "%(sales_open)s" in sql
    assert params["sales_open"] is False
    assert response.json() == {
        "current": {"count": 0},
        "history": [{"business_date": "2026-07-13", "match_count": 6}],
        "sales_window": {
            "is_open": False,
            "message": "官方竞彩休市中，今日 11:00 恢复开售",
        },
    }
