from unittest.mock import patch


def test_strict_official_catalog_migration_rebuilds_dependent_views_safely():
    from pathlib import Path

    sql = Path("sql/31_strict_official_event_catalog.sql").read_text()
    assert sql.index("DROP VIEW IF EXISTS competition_data_coverage") < sql.index(
        "DROP VIEW IF EXISTS event_match_catalog"
    )
    assert "DROP TABLE IF EXISTS official_season_matches" in sql
    assert "DROP TABLE IF EXISTS supplemental_matches" in sql
    assert "ALTER COLUMN source_match_id SET NOT NULL" in sql


def test_events_summarize_only_canonical_official_matches(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.side_effect = [
            [("世界杯", 2, "2026-07-11T00:00:00", "2026-07-11T03:00:00")]
        ]

        response = client.get("/api/events")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    sql = cursor.execute.call_args.args[0]
    assert "event_match_catalog" in sql
    assert "source = 'official'" in sql
    assert "source_match_code IS NOT NULL" in sql


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


def test_active_matches_require_canonical_official_match_codes(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        response = client.get("/api/matches/active")

    assert response.status_code == 200
    sql = cursor.execute.call_args.args[0]
    assert "m.official_match_code ~ '^周[一二三四五六日][0-9]{3}$'" in sql


def test_active_matches_mark_started_unsettled_matches_as_awaiting_result(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (1, "中超", "上海海港", "北京国安", "2026-07-12T19:35:00", "awaiting_result", "周日001")
        ]

        response = client.get("/api/matches/active")

    assert response.status_code == 200
    assert response.json()["matches"][0]["match_status"] == "awaiting_result"
    sql = cursor.execute.call_args.args[0]
    assert "m.kickoff_time <= CURRENT_TIMESTAMP" in sql
    assert "awaiting_result" in sql


def test_active_matches_prioritize_upcoming_over_unsettled_history(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []

        response = client.get("/api/matches/active")

    assert response.status_code == 200
    sql = " ".join(cursor.execute.call_args.args[0].split())
    assert (
        "ORDER BY CASE WHEN m.kickoff_time > CURRENT_TIMESTAMP THEN 0 ELSE 1 END"
        in sql
    )
