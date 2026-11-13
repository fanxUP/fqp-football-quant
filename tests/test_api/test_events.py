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


def test_match_page_returns_true_total_and_evidence_without_relabeling(client):
    from datetime import datetime

    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        cursor = (
            get_db.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        )
        cursor.fetchone.return_value = (
            [{"match_id": 1, "match_status": "Playing", "result_status": "missing"}],
            601,
            50,
            ["中超"],
            ["Playing"],
            False,
            False,
            1,
        )
        with patch(
            "apps.backend.src.services.match_catalog.business_now",
            return_value=datetime(2026, 11, 13, 12),
        ):
            response = client.get("/api/matches/active?limit=1&offset=50")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 601
    assert body["offset"] == 50
    assert body["matches"][0]["match_status"] == "Playing"
    assert body["matches"][0]["result_status"] == "missing"


def test_match_catalog_rejects_invalid_parameters_without_reading_database(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        for suffix in [
            "scope=history",
            "limit=0",
            "offset=-1",
            "sort=unsafe",
            "scope=current&date_from=2026-10-31",
            "scope=history&date_from=2026-10-31&date_to=2026-10-01",
        ]:
            assert client.get("/api/matches/active?" + suffix).status_code == 422
        get_db.assert_not_called()
