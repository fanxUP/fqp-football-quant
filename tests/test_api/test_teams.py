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

    def test_today_matches_use_shanghai_business_date(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            response = client.get("/api/matches/today")

        assert response.status_code == 200
        query = mock_cur.execute.call_args.args[0]
        assert "timezone('Asia/Shanghai', NOW())::date" in query


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
        #          home_team_name, away_team_name, league_name,
        #          official_match_code, kickoff_time, match_num_str
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (
                1,
                101,
                now,
                "v2.1",
                201,
                301,
                0.85,
                0.12,
                3,
                4,
                -1,
                "曼联",
                "利物浦",
                "英超",
                "001",
                now,
                "周三001",
            ),
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
        assert s["official_match_code"] == "001"
        assert s["match_num_str"] == "周三001"

    def test_handles_null_completeness(self, client):
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (
                1,
                101,
                now,
                "v2.1",
                201,
                301,
                None,
                None,
                3,
                4,
                -1,
                "曼联",
                "利物浦",
                "英超",
                "001",
                now,
                "周三001",
            ),
        ]

        with patch("apps.backend.src.routers.teams.get_db", return_value=mock_conn):
            resp = client.get("/api/features/snapshots?limit=10")
        assert resp.status_code == 200
        s = resp.json()["snapshots"][0]
        assert s["data_completeness_score"] is None
        assert s["uncertainty_score"] is None


def test_match_detail_uses_latest_prematch_features_and_all_option_predictions(client):
    now = datetime(2026, 7, 14, 12, 0, 0)
    match_row = (
        101,
        "英超",
        "曼联",
        "利物浦",
        now,
        "Settled",
        "closed",
        None,
        None,
        2,
        1,
        "3",
        "confirmed",
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
    )
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.side_effect = [match_row, None, None, None, None]
    cur.fetchall.return_value = []

    with patch("apps.backend.src.routers.teams.get_db", return_value=conn):
        response = client.get("/api/matches/101/detail")

    assert response.status_code == 200
    queries = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    feature_query = next(q for q in queries if "FROM match_feature_snapshots" in q)
    prediction_query = next(q for q in queries if "FROM model_predictions mp" in q)
    assert "snapshot_time <" in feature_query
    assert "mp.predict_time <" in prediction_query
    assert "mp.validation_status = 'valid'" in prediction_query
    assert "DISTINCT ON (mv.model_name, mp.play_type, mp.option_code)" in prediction_query
