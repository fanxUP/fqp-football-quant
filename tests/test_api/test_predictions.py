"""Integration tests for predictions and tickets endpoints."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch


class TestPredictionsEndpoint:
    def test_live_recommendations_require_actionable_official_evidence(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/recommendations/live")

        assert resp.status_code == 200
        sql = mock_cur.execute.call_args.args[0]
        assert "m.sale_status = 'selling'" in sql
        assert "m.kickoff_time > timezone('Asia/Shanghai', NOW())" in sql
        assert "mp.predict_time < m.kickoff_time" in sql
        assert (
            "m.sale_stop_time IS NULL OR m.sale_stop_time > timezone('Asia/Shanghai', NOW())" in sql
        )
        assert "mp.odds_snapshot_id IS NOT NULL" in sql
        assert "mp.feature_snapshot_id IS NOT NULL" in sql
        assert "mv.is_active = true" in sql
        assert "official_markets" in sql
        normalized = " ".join(sql.split())
        assert (
            "DISTINCT ON (mp.match_id, mp.model_version_id, mp.play_type, mp.option_code)"
            in normalized
        )
        assert "best_by_option" in normalized
        assert normalized.index("best_by_option") < normalized.index("WHERE ev > %(min_ev)s")
        latest_clause = normalized.split("), best_by_option AS", maxsplit=1)[0]
        assert "LEFT JOIN LATERAL" not in latest_clause
        assert normalized.index("FROM best_by_option") < normalized.index("LEFT JOIN LATERAL")

    def test_returns_empty_when_no_predictions(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/predictions?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["predictions"] == []
        sql = mock_cur.execute.call_args.args[0]
        assert "mp.predict_time < m.kickoff_time" in sql

    def test_returns_predictions_with_expected_fields(self, client):
        # Columns: id, match_id, predict_time, model_name, play_type, option_code,
        #          raw_model_probability, model_probability, market_probability, fair_odds, ev, confidence_score,
        #          home_team_name, away_team_name
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
                "xgboost_v2",
                "SPF",
                "胜",
                0.40,
                0.45,
                0.42,
                2.22,
                0.05,
                0.85,
                "曼联",
                "利物浦",
            ),
        ]

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/predictions?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        p = data["predictions"][0]
        assert p["match_id"] == 101
        assert p["model_name"] == "xgboost_v2"
        assert p["raw_model_probability"] == 0.4
        assert p["model_probability"] == 0.45
        assert p["feature_adjusted"] is True
        assert p["ev"] == 0.05
        assert p["home_team"] == "曼联"

    def test_handles_null_probabilities(self, client):
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
                "poisson_v1",
                "SPF",
                "胜",
                None,
                None,
                None,
                None,
                None,
                None,
                "曼联",
                "利物浦",
            ),
        ]

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/predictions?limit=10")
        assert resp.status_code == 200
        p = resp.json()["predictions"][0]
        assert p["model_probability"] is None
        assert p["ev"] is None


class TestTicketsEndpoint:
    def test_returns_empty_when_no_tickets(self, client):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/tickets?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tickets"] == []

    def test_returns_tickets_with_status(self, client):
        # Columns: id, strategy_pool, pass_type, suggested_stake, estimated_return,
        #          expected_value, risk_level, ticket_status, created_at, item_count
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (1, "conservative", "单关", 100.0, 250.0, 0.15, "low", "generated", now, 3),
        ]

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/tickets?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tickets"]) == 1
        t = data["tickets"][0]
        assert t["strategy_pool"] == "conservative"
        assert t["status"] == "generated"
        assert t["risk_level"] == "low"
        assert t["suggested_stake"] == 100.0
        assert t["item_count"] == 3

    def test_handles_null_expected_return(self, client):
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (1, "aggressive", "2串1", 50.0, None, None, "high", "generated", now, 2),
        ]

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            resp = client.get("/api/tickets?limit=10")
        assert resp.status_code == 200
        t = resp.json()["tickets"][0]
        assert t["estimated_return"] is None
        assert t["suggested_stake"] == 50.0
