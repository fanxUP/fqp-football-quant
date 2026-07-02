"""Integration tests for teams and features endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch


class TestTeamsEndpoint:
    def test_returns_empty_list_when_no_teams(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["teams"] == []

    def test_returns_team_mappings(self, client):
        # Columns: id, team_code, team_name_cn, team_name_en, country, short_name, alias_count, profile_count
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (1, "MUFC", "曼联", "Manchester United", "英格兰", "曼联", 3, 1),
            (2, "RM", "皇家马德里", "Real Madrid", "西班牙", "皇马", 2, 1),
        ]

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/teams")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert len(data["teams"]) == 2
        assert data["teams"][0]["team_name_cn"] == "曼联"
        assert data["teams"][0]["team_code"] == "MUFC"

class TestFeaturesSnapshotsEndpoint:
    def test_returns_empty_list_when_no_snapshots(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/features/snapshots?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["snapshots"] == []
        assert data["total"] == 0

    def test_returns_snapshots_with_fields(self, client):
        # Columns: id, match_id, snapshot_time, feature_version,
        #          home_team_id, away_team_id,
        #          data_completeness_score, uncertainty_score,
        #          home_rest_days, away_rest_days, rest_days_diff,
        #          home_team_name, away_team_name, league_name
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (1, 101, now, "v2.1", 201, 301, 0.85, 0.12, 3, 4, -1, "曼联", "利物浦", "英超"),
        ]

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/features/snapshots?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["snapshots"]) == 1
        s = data["snapshots"][0]
        assert s["match_id"] == 101
        assert s["home_team_name"] == "曼联"
        assert s["away_team_name"] == "利物浦"
        assert s["league_name"] == "英超"
        assert s["data_completeness_score"] == 0.85

    def test_handles_null_completeness(self, client):
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (1, 101, now, "v2.1", 201, 301, None, None, 3, 4, -1, "曼联", "利物浦", "英超"),
        ]

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/features/snapshots?limit=10")
        assert resp.status_code == 200
        s = resp.json()["snapshots"][0]
        assert s["data_completeness_score"] is None
        assert s["uncertainty_score"] is None
