"""Integration tests for predictions and tickets endpoints."""

from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch


class TestPredictionsEndpoint:
    def test_live_recommendations_are_unavailable_during_official_rest_time(self, client):
        closed_window = MagicMock(is_open=False)
        closed_window.as_dict.return_value = {
            "is_open": False,
            "message": "官方竞彩休市中，今日 11:00 恢复开售",
        }

        with (
            patch(
                "apps.backend.src.routers.predictions.get_sporttery_sales_window",
                return_value=closed_window,
            ),
            patch("apps.backend.src.routers.predictions.get_db") as get_db,
        ):
            response = client.get("/api/recommendations/live")

        assert response.status_code == 200
        assert response.json() == {
            "status": "resting",
            "recommendations": [],
            "total": 0,
            "sales_window": {
                "is_open": False,
                "message": "官方竞彩休市中，今日 11:00 恢复开售",
            },
        }
        get_db.assert_not_called()

    def test_live_recommendations_require_actionable_official_evidence(self, client):
        open_window = MagicMock(is_open=True)
        open_window.as_dict.return_value = {"is_open": True}
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = []

        with (
            patch(
                "apps.backend.src.routers.predictions.get_sporttery_sales_window",
                return_value=open_window,
            ),
            patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn),
        ):
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
        assert "mp.validation_status = 'valid'" in sql
        assert "model_independent" in sql
        # A released ticket is immutable decision evidence. Retraining may
        # supersede its model version, but must not make the ticket disappear.
        assert "mv.is_active = true" not in sql
        assert "simulation_tickets" in sql
        assert "simulation_ticket_items" in sql
        assert "current_odds.sp_value" in sql
        assert "AS market_probability" in sql
        assert "official_markets" in sql
        normalized = " ".join(sql.split())
        assert (
            "(st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date "
            "= timezone('Asia/Shanghai', NOW())::date"
        ) in normalized
        assert "st.ticket_status IN ('generated', 'activated', 'purchased')" in normalized
        assert "CASE WHEN sti.play_type IN ('spf', 'rqspf') THEN CASE sti.option_code" in normalized

    def test_live_recommendation_exposes_current_official_sp_separately_from_fair_odds(
        self, client
    ):
        open_window = MagicMock(is_open=True)
        open_window.as_dict.return_value = {"is_open": True}
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (
                91,
                26257,
                "spf",
                "3",
                0.5119,
                0.1405,
                1.9537,
                2.2247,
                0.4792,
                datetime(2026, 7, 22, 12, 15),
                "elo_rating",
                "沙佩科恩斯",
                "弗拉门戈",
                "巴西甲级联赛",
                datetime(2026, 7, 23, 8, 30),
                "scheduled",
                None,
                "周三207",
                6.30,
                datetime(2026, 7, 22, 12, 20),
                92.0,
                "agent_competition_observation",
                "high",
            )
        ]

        with (
            patch(
                "apps.backend.src.routers.predictions.get_sporttery_sales_window",
                return_value=open_window,
            ),
            patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn),
        ):
            response = client.get("/api/recommendations/live")

        recommendation = response.json()["recommendations"][0]
        assert recommendation["sp_value"] == 6.3
        assert recommendation["fair_odds"] == 1.95
        assert recommendation["ev"] == 2.2247
        assert recommendation["break_even_probability"] == 0.1587
        assert recommendation["market_edge"] == 0.3714
        assert recommendation["data_completeness"] == 92.0
        assert recommendation["model_independent"] is True
        assert recommendation["strategy_pool"] == "agent_competition_observation"
        assert recommendation["risk_level"] == "high"

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
        assert "mp.validation_status = 'valid'" in sql

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


class TestModelVersionsEndpoint:
    def test_returns_training_date_range_from_current_schema(self, client):
        now = datetime(2026, 7, 22, 14, 41, 37)
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_cur.fetchall.return_value = [
            (
                9,
                "maher_poisson",
                "mle-20260722T144137727716",
                {"n_matches": 4852},
                date(2023, 3, 23),
                date(2026, 7, 21),
                True,
                now,
            )
        ]

        with patch("apps.backend.src.routers.predictions.get_db", return_value=mock_conn):
            response = client.get("/api/models/versions")

        assert response.status_code == 200
        sql = mock_cur.execute.call_args.args[0]
        assert "training_start_date" in sql
        assert "training_end_date" in sql
        assert "training_window_start" not in sql
        version = response.json()["versions"][0]
        assert version["training_start_date"] == "2023-03-23"
        assert version["training_end_date"] == "2026-07-21"
        # Keep the original response names compatible with older clients.
        assert version["training_window_start"] == "2023-03-23"
        assert version["training_window_end"] == "2026-07-21"


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
