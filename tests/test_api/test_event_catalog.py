from unittest.mock import patch


def test_event_catalog_rejects_non_official_sources(client):
    assert client.get("/api/events/catalog?source=supplemental").status_code == 422
    assert client.get("/api/events/catalog?source=official_season").status_code == 422


def test_event_catalog_defaults_to_official_and_supports_explicit_season_dates(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        response = client.get(
            "/api/events/catalog?start_date=2026-01-01&end_date=2026-07-11&limit=5000"
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "official"
    sql, params = cursor.execute.call_args.args
    assert "source = %s" in sql
    assert "source_match_code IS NOT NULL" in sql
    assert "kickoff_time::date >= %s" in sql
    assert "kickoff_time::date <= %s" in sql
    assert params == ("official", "2026-01-01", "2026-07-11", 5000, 0)


def test_event_catalog_returns_total_count_for_pagination(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = (5179,)

        response = client.get("/api/events/catalog?source=official&limit=50&offset=100")

    assert response.status_code == 200
    assert response.json()["total"] == 5179
    _, params = cursor.execute.call_args.args
    assert params == ("official", 50, 100)
