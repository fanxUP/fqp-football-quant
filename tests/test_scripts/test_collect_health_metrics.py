"""Health snapshots must degrade when required audits have no samples."""

from unittest.mock import MagicMock, patch

from scripts.jobs.collect_health_metrics import run


def test_health_is_degraded_when_audit_samples_are_missing():
    conn = MagicMock()
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    with (
        patch("scripts.jobs.collect_health_metrics.get_db", return_value=db_context),
        patch("scripts.jobs.collect_health_metrics._compute_official_collection_rate", return_value={"rate": 1.0, "total_official_matches": 1, "successful_official_collections": 1}),
        patch("scripts.jobs.collect_health_metrics._compute_odds_missing_rate", return_value={"rate": 0.0, "total_odds_snapshots_expected": 1, "missing_odds_snapshots": 0}),
        patch("scripts.jobs.collect_health_metrics._compute_review_generation_rate", return_value={"rate": 1.0, "total_reviews_expected": 1, "successful_review_generations": 1}),
        patch("scripts.jobs.collect_health_metrics.get_backup_success_rate", return_value={"success_rate": 1.0}),
        patch("scripts.jobs.collect_health_metrics.get_evidence_chain_stats", return_value={"completeness_rate": None, "complete_chains": 0, "unique_recommendations": 0, "has_data": False}),
        patch("scripts.jobs.collect_health_metrics.get_contamination_stats", return_value={"contamination_found": 0, "critical_found": 0, "total_checks": 0, "has_data": False}),
        patch("scripts.jobs.collect_health_metrics._compute_uptime_days", return_value=1),
        patch("scripts.jobs.collect_health_metrics._check_system_services", return_value={"scheduler_running": False, "worker_running": False, "api_responding": True, "db_responding": True}),
        patch("scripts.jobs.collect_health_metrics._get_disk_usage", return_value=10.0),
    ):
        result = run(dry_run=True)

    assert result["overall_health"] == "degraded"
    assert result["metrics"]["data_contamination_count"] is None
    assert "证据链暂无审计样本" in result["notes"]
    assert "污染审计暂无样本" in result["notes"]
