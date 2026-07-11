"""Integration tests for ops, backtests, and reviews endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_db_conn(fetchall=None, fetchone=None, description=None):
    """Create a mock connection for use with `with get_db() as conn:`."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = fetchall if fetchall is not None else []
    mock_cur.fetchone.return_value = fetchone
    if description is not None:
        mock_cur.description = description
    return mock_conn, mock_cur


class TestBacktestsEndpoint:
    def test_lists_backtests_empty(self, client):
        mock_conn, mock_cur = _mock_db_conn(
            fetchall=[],
            fetchone=[0],
            description=[
                ("id",), ("name",), ("description",), ("config",), ("status",),
                ("started_at",), ("finished_at",), ("error_message",), ("created_at",),
            ],
        )

        with patch("apps.backend.src.routers.backtests.get_db", return_value=mock_conn):
            resp = client.get("/api/backtests?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "runs" in data
        assert data["runs"] == []
        assert data["total"] == 0

    def test_lists_backtests_with_data(self, client):
        from datetime import datetime
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn, mock_cur = _mock_db_conn(
            fetchall=[
                (1, "baseline_v1", "Initial backtest", '{"model":"xgboost"}', "completed",
                 now, now, None, now),
            ],
            fetchone=[1],
            description=[
                ("id",), ("name",), ("description",), ("config",), ("status",),
                ("started_at",), ("finished_at",), ("error_message",), ("created_at",),
            ],
        )

        with patch("apps.backend.src.routers.backtests.get_db", return_value=mock_conn):
            resp = client.get("/api/backtests?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "baseline_v1"
        assert data["runs"][0]["status"] == "completed"

    def test_backtest_not_found(self, client):
        mock_conn, mock_cur = _mock_db_conn(
            fetchone=None,
            description=[
                ("id",), ("name",), ("description",), ("config",), ("status",),
                ("started_at",), ("finished_at",), ("error_message",), ("created_at",),
            ],
        )

        with patch("apps.backend.src.routers.backtests.get_db", return_value=mock_conn):
            resp = client.get("/api/backtests/999")
        # Endpoint returns 200 with error message, not 404
        assert resp.status_code == 200
        assert resp.json()["error"] == "not found"


class TestOpsHealth:
    def test_returns_no_data_when_no_snapshots(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn), \
             patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=None):
            resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "no_data"

    def test_returns_snapshot_data(self, client):
        mock_conn, mock_cur = _mock_db_conn()
        snapshot = {
            "overall_health_status": "healthy",
            "snapshot_date": "2025-01-01T10:00:00",
            "continuous_uptime_days": 30,
            "official_collection_success_rate": 0.95,
            "odds_snapshot_missing_rate": 0.02,
            "review_generation_success_rate": 1.0,
            "backup_success": True,
            "evidence_chain_completeness_rate": 0.99,
            "data_contamination_count": 0,
            "scheduler_running": True,
            "worker_running": True,
            "api_responding": True,
            "db_responding": True,
            "disk_usage_pct": 45.0,
            "health_notes": "All systems normal",
        }

        with patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn), \
             patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=snapshot):
            resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["metrics"]["uptime_days"] == 30
        assert data["services"]["db"] is True


class TestReviewsEndpoint:
    def test_daily_reviews_returns_list(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn), \
             patch("apps.backend.src.routers.tickets._list_daily_reviews", return_value=[]):
            resp = client.get("/api/reviews/daily?limit=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "reviews" in data
        assert data["reviews"] == []

    def test_weekly_reviews_returns_list(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn), \
             patch("apps.backend.src.routers.tickets._list_weekly_reviews", return_value=[]):
            resp = client.get("/api/reviews/weekly?limit=12")
        assert resp.status_code == 200
        data = resp.json()
        assert "reviews" in data

    def test_daily_review_by_date_not_found(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn), \
             patch("apps.backend.src.routers.tickets._get_daily_review", return_value=None):
            resp = client.get("/api/reviews/daily/2099-01-01")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"
