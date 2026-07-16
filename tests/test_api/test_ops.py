"""Integration tests for ops, backtests, and reviews endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from apps.backend.src.services.pipeline_status import _is_stale


def test_pipeline_treats_missing_and_future_timestamps_as_stale():
    now = datetime(2026, 7, 15, 3, 0, tzinfo=UTC)

    assert _is_stale(None, timedelta(minutes=5), now) is True
    assert _is_stale(datetime(2026, 7, 15, 4, 0), timedelta(minutes=5), now) is True


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
                ("id",),
                ("name",),
                ("description",),
                ("config",),
                ("status",),
                ("started_at",),
                ("finished_at",),
                ("error_message",),
                ("created_at",),
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
        now = datetime(2025, 1, 1, 10, 0, 0)
        mock_conn, mock_cur = _mock_db_conn(
            fetchall=[
                (
                    1,
                    "baseline_v1",
                    "Initial backtest",
                    '{"model":"xgboost"}',
                    "completed",
                    now,
                    now,
                    None,
                    now,
                ),
            ],
            fetchone=[1],
            description=[
                ("id",),
                ("name",),
                ("description",),
                ("config",),
                ("status",),
                ("started_at",),
                ("finished_at",),
                ("error_message",),
                ("created_at",),
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
                ("id",),
                ("name",),
                ("description",),
                ("config",),
                ("status",),
                ("started_at",),
                ("finished_at",),
                ("error_message",),
                ("created_at",),
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

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=None),
        ):
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

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=snapshot),
            patch(
                "apps.backend.src.routers.ops.get_live_service_status",
                return_value={
                    "scheduler_running": True,
                    "worker_running": True,
                    "api_responding": True,
                    "db_responding": True,
                },
            ),
        ):
            resp = client.get("/api/ops/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["metrics"]["uptime_days"] == 30
        assert data["services"]["db"] is True

    def test_live_service_failure_overrides_stale_healthy_snapshot(self, client):
        mock_conn, _ = _mock_db_conn()
        snapshot = {
            "overall_health_status": "healthy",
            "snapshot_date": "2026-07-15",
            "snapshot_time": "2026-07-15T03:55:00",
            "scheduler_running": True,
            "worker_running": True,
            "api_responding": True,
            "db_responding": True,
            "health_notes": "All systems normal",
        }

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=snapshot),
            patch(
                "apps.backend.src.routers.ops.get_live_service_status",
                return_value={
                    "scheduler_running": False,
                    "worker_running": True,
                    "api_responding": True,
                    "db_responding": True,
                },
            ),
        ):
            resp = client.get("/api/ops/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "critical"
        assert resp.json()["services"]["scheduler"] is False
        assert "Scheduler 心跳中断" in resp.json()["notes"]

    def test_returns_snapshot_time_as_explicit_utc(self, client):
        mock_conn, _ = _mock_db_conn()
        snapshot = {
            "overall_health_status": "healthy",
            "snapshot_date": "2026-07-15",
            "snapshot_time": "2026-07-15T03:55:00",
        }

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.ops.get_latest_health_snapshot", return_value=snapshot),
        ):
            resp = client.get("/api/ops/health")

        assert resp.status_code == 200
        assert resp.json()["snapshot_time"] == "2026-07-15T03:55:00Z"


class TestOpsPipeline:
    def test_hides_retired_source_health_rows(self, client):
        mock_conn, mock_cur = _mock_db_conn()
        mock_cur.fetchall.side_effect = [
            [
                (1, "sporttery", "results", "ok", datetime(2026, 7, 15, 3, 8), None, 0, 200),
                (2, "500.com", "supplemental", "ok", datetime(2026, 7, 15, 1, 0), None, 0, 300),
            ],
            [],
        ]

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch(
                "apps.backend.src.services.pipeline_status._utc_now",
                return_value=datetime(2026, 7, 15, 3, 9, tzinfo=UTC),
            ),
        ):
            response = client.get("/api/ops/pipeline")

        assert response.status_code == 200
        assert response.json()["sources"] == [
            {
                "name": "sporttery",
                "source_type": "results",
                "status": "ok",
                "last_success": "2026-07-15T03:08:00Z",
                "last_failure": None,
                "failures": 0,
                "latency_ms": 200,
            }
        ]

    def test_normalizes_active_jobs_sources_and_utc_timestamps(self, client):
        mock_conn, mock_cur = _mock_db_conn()
        mock_cur.fetchall.side_effect = [
            [
                (1, "sporttery", "results", "error", None, datetime(2026, 7, 15, 3, 0, 2), 192, 0),
                (
                    4,
                    "sporttery",
                    "traditional_lottery",
                    "ok",
                    datetime(2026, 7, 15, 3, 7, 2),
                    None,
                    5,
                    1909,
                ),
                (5, "sporttery", "official", "ok", datetime(2026, 7, 15, 3, 8, 0), None, 0, 200),
                (6, "500.com", "supplemental", "ok", datetime(2026, 7, 15, 3, 8, 1), None, 0, 300),
                (7, "500.com", "official", "ok", datetime(2026, 7, 10, 3, 8, 0), None, 0, 400),
            ],
            [
                (101, "official_odds_snapshot", "completed", datetime(2026, 7, 15, 3, 8, 19), None, None),
                (99, "crawl_official_odds", "success", datetime(2026, 7, 9, 23, 30), None, None),
                (
                    88,
                    "refresh_supplemental_seasons",
                    "failed",
                    datetime(2026, 7, 13, 3, 40),
                    "obsolete table",
                    None,
                ),
            ],
        ]

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch(
                "apps.backend.src.services.pipeline_status._utc_now",
                return_value=datetime(2026, 7, 15, 3, 9, tzinfo=UTC),
            ),
        ):
            resp = client.get("/api/ops/pipeline")

        assert resp.status_code == 200
        data = resp.json()
        assert data["sources"][0] == {
            "name": "sporttery",
            "source_type": "results",
            "status": "error",
            "last_success": None,
            "last_failure": "2026-07-15T03:00:02Z",
            "failures": 192,
            "latency_ms": 0,
        }
        assert {source["source_type"] for source in data["sources"]} == {
            "results",
            "traditional_lottery",
        }
        odds_job = next(job for job in data["jobs"] if job["code"] == "official_odds_snapshot")
        assert odds_job == {
            "code": "official_odds_snapshot",
            "name": "赔率快照采集",
            "status": "success",
            "finished_at": "2026-07-15T03:08:19Z",
            "error": None,
            "detail": None,
            "schedule": "每分钟检查；开盘/每30分钟/开赛时采集",
            "category": "official",
        }
        monthly = next(job for job in data["jobs"] if job["code"] == "generate_monthly_review")
        assert monthly["status"] == "pending"
        assert monthly["finished_at"] is None
        assert len(data["jobs"]) == 30

    def test_pipeline_surfaces_feature_quality_degradation_from_job_output(self, client):
        mock_conn, mock_cur = _mock_db_conn()
        mock_cur.fetchall.side_effect = [
            [],
            [(
                102,
                "feature_snapshot_build",
                "ok",
                datetime(2026, 7, 15, 3, 8, 19),
                None,
                {
                    "result": {
                        "quality_status": "degraded",
                        "average_completeness": 22.5,
                    }
                },
            )],
        ]

        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch(
                "apps.backend.src.services.pipeline_status._utc_now",
                return_value=datetime(2026, 7, 15, 3, 9, tzinfo=UTC),
            ),
        ):
            response = client.get("/api/ops/pipeline")

        job = next(
            item for item in response.json()["jobs"]
            if item["code"] == "feature_snapshot_build"
        )
        assert job["status"] == "degraded"
        assert job["detail"] == "平均特征完整度 22.5%"


class TestOpsAuditGates:
    def test_evidence_chain_does_not_pass_without_audited_samples(self, client):
        mock_conn, _ = _mock_db_conn()
        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch(
                "apps.backend.src.routers.ops.get_evidence_chain_stats",
                return_value={
                    "total_audited": 0,
                    "complete_chains": 0,
                    "unique_recommendations": 0,
                    "completeness_rate": None,
                    "has_data": False,
                },
            ),
        ):
            resp = client.get("/api/ops/evidence-chain")

        assert resp.status_code == 200
        assert resp.json()["status"] == "no_data"
        assert resp.json()["passes_stage8"] is False

    def test_contamination_audit_does_not_pass_without_checks(self, client):
        mock_conn, _ = _mock_db_conn()
        with (
            patch("apps.backend.src.routers.ops.get_db", return_value=mock_conn),
            patch(
                "apps.backend.src.routers.ops.get_contamination_stats",
                return_value={
                    "total_checks": 0,
                    "contamination_found": 0,
                    "critical_found": 0,
                    "has_data": False,
                },
            ),
            patch("apps.backend.src.routers.ops.get_recent_contamination_issues", return_value=[]),
        ):
            resp = client.get("/api/ops/contamination-audit")

        assert resp.status_code == 200
        assert resp.json()["status"] == "no_data"
        assert resp.json()["passes_stage8"] is False


class TestReviewsEndpoint:
    def test_daily_reviews_returns_list(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with (
            patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.tickets._list_daily_reviews", return_value=[]),
        ):
            resp = client.get("/api/reviews/daily?limit=30")
        assert resp.status_code == 200
        data = resp.json()
        assert "reviews" in data
        assert data["reviews"] == []

    def test_weekly_reviews_returns_list(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with (
            patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.tickets._list_weekly_reviews", return_value=[]),
        ):
            resp = client.get("/api/reviews/weekly?limit=12")
        assert resp.status_code == 200
        data = resp.json()
        assert "reviews" in data

    def test_daily_review_by_date_not_found(self, client):
        mock_conn, mock_cur = _mock_db_conn()

        with (
            patch("apps.backend.src.routers.tickets.get_db", return_value=mock_conn),
            patch("apps.backend.src.routers.tickets._get_daily_review", return_value=None),
        ):
            resp = client.get("/api/reviews/daily/2099-01-01")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"
