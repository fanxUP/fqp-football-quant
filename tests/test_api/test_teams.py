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


def _roster_detail_cursor():
    """Dispatch SQL mocks by query, avoiding unrelated detail-query ordering."""
    conn, cur = MagicMock(), MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    state = {"query": "", "args": ()}

    def execute(query, args):
        state.update(query=query, args=args)

    def one():
        query = state["query"]
        if "FROM official_matches m" in query and "WHERE m.id = %s" in query:
            return (
                101,
                "联赛",
                "主队",
                "客队",
                datetime(2026, 10, 9, 20),
                "Selling",
                "selling",
                None,
                None,
                None,
                None,
                None,
                None,
                1,
                "主队",
                None,
                None,
                None,
                2,
                "客队",
                None,
                None,
                None,
            )
        if "FROM match_lineup_snapshots" in query and state["args"][1] == 1:
            return (
                11,
                "4-3-3",
                0,
                0,
                0,
                "confirmed",
                "来源",
                datetime(2026, 10, 9, 19),
                datetime(2026, 10, 9, 19, 5),
                101,
                1,
            )
        return None

    def many():
        if "FROM match_lineup_players" in state["query"]:
            return [(7, True, False, "DF", "边路", "球员", None, "DF")]
        if "player_availability_snapshots" in state["query"] and state["args"][0] == 1:
            return [
                (
                    1,
                    "injured",
                    "旧伤",
                    None,
                    None,
                    0,
                    "球员",
                    None,
                    "DF",
                    7,
                    51,
                    "伤停来源",
                    datetime(2026, 10, 10, 10),
                    datetime(2026, 10, 10, 10, 5),
                )
            ]
        return []

    cur.execute.side_effect = execute
    cur.fetchone.side_effect = one
    cur.fetchall.side_effect = many
    return conn, cur


def test_match_roster_includes_source_time_identity_and_real_zero(client):
    conn, _ = _roster_detail_cursor()
    with patch("apps.backend.src.routers.teams.get_db", return_value=conn):
        response = client.get("/api/matches/101/detail")
    assert response.status_code == 200
    lineup = response.json()["lineups"]["home"]
    assert lineup["snapshot_id"] == 11
    assert lineup["match_id"] == 101 and lineup["team_id"] == 1
    assert lineup["source"] == "来源"
    assert lineup["snapshot_time"] == "2026-10-09T19:00:00"
    assert lineup["collected_at"] == "2026-10-09T19:05:00"
    assert lineup["strength_score"] == 0 and lineup["starting_11_value"] == 0
    assert "jersey_number" not in lineup["players"][0]


def test_latest_availability_is_selected_before_filtering_injured_status(client):
    conn, cur = _roster_detail_cursor()
    with patch("apps.backend.src.routers.teams.get_db", return_value=conn):
        data = client.get("/api/matches/101/detail").json()
    queries = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    query = next(q for q in queries if "player_availability_snapshots" in q)
    assert "DISTINCT ON (player_id)" in query
    assert "ORDER BY player_id, snapshot_time DESC, id DESC" in query
    assert query.index("availability_status IN") > query.index(") latest")
    assert "LIMIT 20" in query
    assert data["availability_scope"] == "latest_per_player_team"
    assert data["availability_limit_per_team"] == 20


def test_injuries_include_player_and_snapshot_provenance_with_zero_score(client):
    conn, _ = _roster_detail_cursor()
    with patch("apps.backend.src.routers.teams.get_db", return_value=conn):
        data = client.get("/api/matches/101/detail").json()
    injury = data["injuries"][0]
    assert injury["player_id"] == 7 and injury["snapshot_id"] == 51
    assert injury["source"] == "伤停来源"
    assert injury["snapshot_time"] == "2026-10-10T10:00:00"
    assert injury["collected_at"] == "2026-10-10T10:05:00"
    assert injury["impact_score"] == 0


def test_latest_lineup_uses_deterministic_snapshot_order(client):
    conn, cur = _roster_detail_cursor()
    with patch("apps.backend.src.routers.teams.get_db", return_value=conn):
        response = client.get("/api/matches/101/detail")
    assert response.status_code == 200
    query = next(
        call.args[0]
        for call in cur.execute.call_args_list
        if "FROM match_lineup_snapshots" in call.args[0]
    )
    assert "ORDER BY mls.snapshot_time DESC, mls.id DESC LIMIT 1" in query
