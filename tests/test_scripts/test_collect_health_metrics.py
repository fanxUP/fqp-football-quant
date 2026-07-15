"""Health snapshots must reflect live services and real calendar uptime."""

from datetime import date
from unittest.mock import MagicMock, patch

from scripts.jobs.collect_health_metrics import (
    _check_system_services,
    _compute_odds_missing_rate,
    _compute_review_generation_rate,
    _compute_uptime_days,
    _get_disk_usage,
    run,
)


def test_review_generation_rate_expects_completed_days_through_yesterday(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.side_effect = [(15,), (date(2026, 6, 30),)]

    result = _compute_review_generation_rate(conn, review_end=date(2026, 7, 14))

    assert result == {
        "total_reviews_expected": 15,
        "successful_review_generations": 15,
        "rate": 1.0,
    }
    query = " ".join(cur.execute.call_args_list[0].args[0].split())
    assert "review_date BETWEEN" in query


def test_health_is_degraded_when_audit_samples_are_missing():
    conn = MagicMock()
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    with (
        patch("scripts.jobs.collect_health_metrics.get_db", return_value=db_context),
        patch(
            "scripts.jobs.collect_health_metrics._compute_official_collection_rate",
            return_value={
                "rate": 1.0,
                "total_official_matches": 1,
                "successful_official_collections": 1,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics._compute_odds_missing_rate",
            return_value={
                "rate": 0.0,
                "total_odds_snapshots_expected": 1,
                "missing_odds_snapshots": 0,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics._compute_review_generation_rate",
            return_value={
                "rate": 1.0,
                "total_reviews_expected": 1,
                "successful_review_generations": 1,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_backup_success_rate",
            return_value={"success_rate": 1.0},
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_evidence_chain_stats",
            return_value={
                "completeness_rate": None,
                "complete_chains": 0,
                "unique_recommendations": 0,
                "has_data": False,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_contamination_stats",
            return_value={
                "contamination_found": 0,
                "critical_found": 0,
                "total_checks": 0,
                "has_data": False,
            },
        ),
        patch("scripts.jobs.collect_health_metrics._compute_uptime_days", return_value=1),
        patch(
            "scripts.jobs.collect_health_metrics._check_system_services",
            return_value={
                "scheduler_running": True,
                "worker_running": True,
                "api_responding": True,
                "db_responding": True,
            },
        ),
        patch("scripts.jobs.collect_health_metrics._get_disk_usage", return_value=10.0),
    ):
        result = run(dry_run=True)

    assert result["overall_health"] == "degraded"
    assert result["metrics"]["data_contamination_count"] is None
    assert "证据链暂无审计样本" in result["notes"]
    assert "污染审计暂无样本" in result["notes"]


def test_odds_missing_rate_only_counts_upcoming_selling_matches(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.side_effect = [(4,), (1,)]

    result = _compute_odds_missing_rate(conn)

    queries = [call.args[0] for call in cur.execute.call_args_list]
    assert all("timezone('Asia/Shanghai', NOW())" in query for query in queries)
    assert "INTERVAL '45 minutes'" in queries[1]
    assert result == {
        "total_odds_snapshots_expected": 4,
        "missing_odds_snapshots": 1,
        "rate": 0.25,
    }


def test_health_notes_report_noncritical_unresolved_contamination():
    conn = MagicMock()
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    with (
        patch("scripts.jobs.collect_health_metrics.get_db", return_value=db_context),
        patch(
            "scripts.jobs.collect_health_metrics._compute_official_collection_rate",
            return_value={
                "rate": 1.0,
                "total_official_matches": 1,
                "successful_official_collections": 1,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics._compute_odds_missing_rate",
            return_value={
                "rate": 0.0,
                "total_odds_snapshots_expected": 1,
                "missing_odds_snapshots": 0,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics._compute_review_generation_rate",
            return_value={
                "rate": 1.0,
                "total_reviews_expected": 1,
                "successful_review_generations": 1,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_backup_success_rate",
            return_value={"success_rate": 1.0},
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_evidence_chain_stats",
            return_value={
                "completeness_rate": 1.0,
                "complete_chains": 1,
                "unique_recommendations": 1,
                "has_data": True,
            },
        ),
        patch(
            "scripts.jobs.collect_health_metrics.get_contamination_stats",
            return_value={
                "contamination_found": 2,
                "critical_found": 0,
                "total_checks": 4,
                "has_data": True,
            },
        ),
        patch("scripts.jobs.collect_health_metrics._compute_uptime_days", return_value=1),
        patch(
            "scripts.jobs.collect_health_metrics._check_system_services",
            return_value={
                "scheduler_running": True,
                "worker_running": True,
                "api_responding": True,
                "db_responding": True,
            },
        ),
        patch("scripts.jobs.collect_health_metrics._get_disk_usage", return_value=10.0),
    ):
        result = run(dry_run=True)

    assert result["overall_health"] == "degraded"
    assert "数据污染 2 条待处理" in result["notes"]


def test_uptime_counts_consecutive_snapshot_dates_without_same_day_inflation(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = [
        (date(2026, 7, 14), True, True, True, True),
        (date(2026, 7, 13), True, True, True, True),
        (date(2026, 7, 11), True, True, True, True),
    ]
    services = {
        "scheduler_running": True,
        "worker_running": True,
        "api_responding": True,
        "db_responding": True,
    }

    assert _compute_uptime_days(conn, date(2026, 7, 15), services) == 3


def test_uptime_is_zero_when_a_core_service_is_offline(mock_conn):
    conn, _ = mock_conn
    services = {
        "scheduler_running": False,
        "worker_running": True,
        "api_responding": True,
        "db_responding": True,
    }

    assert _compute_uptime_days(conn, date(2026, 7, 15), services) == 0


def test_service_health_uses_worker_heartbeat_and_real_api_probe():
    with (
        patch("scripts.jobs.collect_health_metrics.is_scheduler_alive", return_value=True),
        patch("scripts.jobs.collect_health_metrics.is_worker_alive", return_value=False),
        patch("scripts.jobs.collect_health_metrics.is_http_service_alive", return_value=False),
    ):
        status = _check_system_services(MagicMock())

    assert status == {
        "scheduler_running": True,
        "worker_running": False,
        "api_responding": False,
        "db_responding": True,
    }


def test_disk_usage_falls_back_to_root_when_configured_path_is_missing(monkeypatch):
    monkeypatch.setenv("FQP_DATA_DIR", "/missing/fqp/data")
    usage = MagicMock(used=25, total=100)

    with patch(
        "scripts.jobs.collect_health_metrics.shutil.disk_usage",
        side_effect=[FileNotFoundError, usage],
    ) as disk_usage:
        assert _get_disk_usage() == 25.0

    assert disk_usage.call_args_list[-1].args == ("/",)
