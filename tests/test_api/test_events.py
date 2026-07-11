from unittest.mock import patch


def test_events_include_scheduled_official_matches(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [("世界杯", 2, "2026-07-11T00:00:00", "2026-07-11T03:00:00")]
        ]

        response = client.get("/api/events")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert "match_status" not in cursor.execute.call_args.args[0]
    assert "scheduled" not in cursor.execute.call_args.args[0]


def test_active_matches_exclude_finished_official_history(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (1, "中超", "上海海港", "北京国安", "2026-07-12T19:35:00", "scheduled", "周日001")
        ]

        response = client.get("/api/matches/active")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    sql = cursor.execute.call_args.args[0]
    completed_statuses = cursor.execute.call_args.args[1][0]
    assert "official_matches" in sql
    assert "NOT IN %s" in sql
    assert "finished" in completed_statuses
    assert "settled" in completed_statuses
