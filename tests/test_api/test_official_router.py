from unittest.mock import patch


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
