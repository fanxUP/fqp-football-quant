from unittest.mock import patch


def test_event_coverage_exposes_source_counts(client):
    with patch("apps.backend.src.routers.teams.get_db") as get_db:
        connection = get_db.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            (
                1,
                "瑞典超级联赛",
                "2026",
                16,
                8,
                236,
                0,
                16,
                "2026-07-11T01:08:05",
                "2026-07-11T01:23:12",
                236,
                0,
            )
        ]

        response = client.get("/api/events/coverage")

    assert response.status_code == 200
    row = response.json()["coverage"][0]
    assert row["official_match_count"] == 8
    assert row["supplemental_standings_snapshot_count"] == 16
    assert row["unmapped_supplemental_match_count"] == 0
