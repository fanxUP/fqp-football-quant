from unittest.mock import patch


def test_event_catalog_preserves_source_label(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                "supplemental",
                7,
                "abc",
                2,
                10,
                11,
                "瑞典超级联赛",
                "A",
                "B",
                "2026-07-11T00:00:00",
                "Settled",
                2,
                1,
            )
        ]

        response = client.get("/api/events/catalog?source=supplemental&limit=10")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "supplemental"
    assert payload["matches"][0]["source"] == "supplemental"
    assert payload["matches"][0]["competition_season_id"] == 2


def test_event_catalog_accepts_official_season_archive_source(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = (0,)

        response = client.get("/api/events/catalog?source=official_season&limit=10")

    assert response.status_code == 200
    assert response.json()["source"] == "official_season"
    _, params = cursor.execute.call_args.args
    assert params == ("official_season", 10, 0)


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
