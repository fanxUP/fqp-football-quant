import re
from datetime import datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.backend.src.services.pipeline_status import JOB_DEFINITIONS
from scripts.jobs.run_scheduler import (
    MODEL_PREDICTION_CRON,
    OFFICIAL_SCHEDULE_CRON,
    SEASON_RECONCILIATION_RETRY_TIME,
    STARTUP_RECOVERY_JOB_CODES,
    _audited_job,
    _business_now,
    _odds_dispatch_owner,
    _scheduler_timezone_name,
    _should_retry_season_reconciliation,
    _should_run_recommendation_catchup,
)


def test_self_tracked_job_is_not_wrapped_again():
    def job():
        return "tracked"

    wrapped = _audited_job("run_model_prediction", "模型预测", "model_agent", job)
    assert wrapped is job


def test_upset_provider_collection_is_not_double_tracked():
    def job():
        return {"status": "skipped"}

    wrapped = _audited_job(
        "collect_upset_provider_evidence",
        "冷门赛中事件与技术统计采集",
        "review_agent",
        job,
    )

    assert wrapped is job


def test_legacy_job_still_gets_scheduler_wrapper():
    def job():
        return "legacy"

    wrapped = _audited_job("legacy_job", "旧任务", "qa_agent", job)
    assert wrapped is not job


def test_scheduler_uses_completed_status_for_successful_legacy_jobs():
    # The wrapper's completion status is part of the shared ai_job_runs contract;
    # inspect the source to keep this test free of a real database side effect.
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'conn, run_id, "completed"' in source
    assert 'finish_job_run(conn, run_id, "success"' not in source


def test_scheduler_recovers_interrupted_legacy_run_before_starting_next_one():
    conn = MagicMock()
    wrapped = _audited_job("settle_tickets", "票单结算", "settlement_agent", lambda: {})

    with (
        patch("apps.backend.src.db.get_db") as get_db,
        patch("scripts.agent_storage.recover_interrupted_job_runs") as recover,
        patch("scripts.agent_storage.start_job_run", return_value=21),
        patch("scripts.agent_storage.finish_job_run"),
    ):
        get_db.return_value.__enter__.return_value = conn
        wrapped()

    recover.assert_called_once_with(
        conn,
        ["settle_tickets"],
        reason="superseded by a new scheduler execution after process interruption",
    )


def test_scheduler_has_no_numberless_match_refresh_path():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert "refresh_supplemental_seasons" not in source
    assert "SUPPLEMENTAL_SEASON_ENABLED" not in source


def test_scheduler_does_not_refresh_numberless_official_season_archive():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'id="refresh_official_seasons"' not in source


def test_scheduler_reconciles_numbered_event_seasons_before_schedule_refresh():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'id="reconcile_event_seasons"' in source
    assert source.index('id="reconcile_event_seasons"') < source.index(
        'id="crawl_official_schedule"'
    )


def test_season_reconciliation_retry_is_limited_to_one_delayed_daily_run():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert SEASON_RECONCILIATION_RETRY_TIME == clock_time(hour=1, minute=5)
    assert 'id="reconcile_event_seasons_retry"' in source


def test_season_reconciliation_retry_requires_a_failed_primary_run_today():
    now = datetime.fromisoformat("2026-08-02T01:05:00+08:00")

    assert _should_retry_season_reconciliation(
        now, "failed", datetime.fromisoformat("2026-08-02T00:05:20+08:00")
    ) is True
    assert _should_retry_season_reconciliation(
        now, "completed", datetime.fromisoformat("2026-08-02T00:05:20+08:00")
    ) is False
    assert _should_retry_season_reconciliation(
        now, "failed", datetime.fromisoformat("2026-08-01T00:05:20+08:00")
    ) is False


def test_scheduler_refreshes_official_schedule_metadata_every_30_minutes():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert OFFICIAL_SCHEDULE_CRON == {"minute": "10,40"}
    assert "**OFFICIAL_SCHEDULE_CRON" in source


def test_scheduler_collects_lineups_in_the_pre_match_window_every_30_minutes():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="collect_lineup_data"' in source
    assert 'minute="12,42"' in source
    assert 'hour="10,14"' not in source


def test_pipeline_schedule_labels_match_enrichment_cron():
    assert JOB_DEFINITIONS["injury_collection"].schedule == "每日 00:07"
    assert JOB_DEFINITIONS["lineup_collection"].schedule == "每30分钟（:12/:42）"


def test_scheduler_refreshes_features_after_lineup_collection_before_prediction():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="refresh_pre_match_features"' in source
    assert 'minute="14,44"' in source


def test_scheduler_runs_model_predictions_after_each_schedule_refresh():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert MODEL_PREDICTION_CRON == {"minute": "15,45"}
    assert "**MODEL_PREDICTION_CRON" in source


def test_scheduler_detects_upsets_after_results_and_ticket_settlement():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="detect_upsets"' in source
    assert 'minute="20,50"' in source
    assert source.index('id="settle_finished_matches"') < source.index('id="detect_upsets"')
    assert source.index('id="settle_tickets"') < source.index('id="detect_upsets"')
    assert source.index('id="detect_upsets"') < source.index('id="generate_daily_review"')


def test_scheduler_builds_upset_evidence_and_review_after_detection():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="collect_upset_provider_evidence"' in source
    assert 'minute="21,51"' in source
    assert 'id="collect_upset_evidence"' in source
    assert 'minute="22,52"' in source
    assert 'id="generate_upset_reviews"' in source
    assert 'minute="25,55"' in source
    assert source.index('id="detect_upsets"') < source.index('id="collect_upset_evidence"')
    assert source.index('id="detect_upsets"') < source.index('id="collect_upset_provider_evidence"')
    assert source.index('id="collect_upset_provider_evidence"') < source.index(
        'id="collect_upset_evidence"'
    )
    assert source.index('id="collect_upset_evidence"') < source.index('id="generate_upset_reviews"')


def test_scheduler_refreshes_upset_knowledge_daily():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="refresh_upset_knowledge"' in source
    assert '"refresh_upset_knowledge"' in source
    assert "hour=11" in source


def test_scheduler_extracts_research_hypotheses_without_auto_promotion():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'id="sync_upset_hypotheses"' in source
    assert '"scripts.jobs.sync_upset_hypotheses"' in source
    assert "transition_hypothesis" not in source


def test_scheduler_dispatches_odds_by_default_for_host_runtime(monkeypatch):
    monkeypatch.delenv("FQP_ODDS_DISPATCH_OWNER", raising=False)

    assert _odds_dispatch_owner() == "scheduler"


def test_scheduler_can_delegate_odds_dispatch_to_worker(monkeypatch):
    monkeypatch.setenv("FQP_ODDS_DISPATCH_OWNER", "worker")

    assert _odds_dispatch_owner() == "worker"


def test_scheduler_guards_odds_dispatch_with_single_owner_setting():
    source = Path("scripts/jobs/run_scheduler.py").read_text()

    assert 'if _odds_dispatch_owner() == "scheduler"' in source
    assert 'id="crawl_official_odds"' in source


def test_high_frequency_odds_dispatch_has_one_worker_owner():
    scheduler_source = Path("scripts/jobs/run_scheduler.py").read_text()
    worker_source = Path("scripts/official_crawler_stub.py").read_text()

    assert 'if _odds_dispatch_owner() == "scheduler"' in scheduler_source
    assert "POLL_INTERVAL_SECONDS = 60" in worker_source
    assert "scripts.jobs.run_official_odds_snapshot" in worker_source


def test_every_monitored_job_has_a_runtime_owner():
    scheduler_source = Path("scripts/jobs/run_scheduler.py").read_text()
    scheduler_ids = set(re.findall(r'id="([^"]+)"', scheduler_source))

    for canonical, definition in JOB_DEFINITIONS.items():
        assert scheduler_ids.intersection((canonical, *definition.aliases)), canonical


def test_scheduler_defaults_to_shanghai_timezone(monkeypatch):
    monkeypatch.delenv("FQP_TIMEZONE", raising=False)

    assert _scheduler_timezone_name() == "Asia/Shanghai"


def test_scheduler_timezone_can_be_overridden(monkeypatch):
    monkeypatch.setenv("FQP_TIMEZONE", "Asia/Hong_Kong")

    assert _scheduler_timezone_name() == "Asia/Hong_Kong"


def test_scheduler_business_time_is_timezone_aware(monkeypatch):
    monkeypatch.setenv("FQP_TIMEZONE", "Asia/Shanghai")

    now = _business_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(hours=8)


def test_scheduler_catches_up_missing_daily_recommendation_after_cutoff():
    now = datetime.fromisoformat("2026-07-14T17:00:00+08:00")

    assert _should_run_recommendation_catchup(now, decision_status=None) is True
    assert _should_run_recommendation_catchup(now, decision_status="failed") is True


def test_scheduler_does_not_duplicate_terminal_daily_decision():
    now = datetime.fromisoformat("2026-07-14T17:00:00+08:00")

    assert _should_run_recommendation_catchup(now, decision_status="purchased") is False
    assert _should_run_recommendation_catchup(now, decision_status="abstained") is False


def test_scheduler_waits_for_daily_recommendation_cutoff():
    now = datetime.fromisoformat("2026-07-14T15:59:59+08:00")

    assert _should_run_recommendation_catchup(now, decision_status=None) is False


def test_scheduler_replays_every_critical_startup_job_until_it_succeeds():
    assert STARTUP_RECOVERY_JOB_CODES == (
        "seed_agent_registry",
        "seed_api_football_registry",
        "seed_stadium_registry",
        "settle_tickets",
        "build_feature_snapshots",
        "run_recommendation_candidate",
    )

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'id="startup_recovery"' in source
    assert 'id="seed_agent_registry"' not in source
    assert 'id="run_recommendation_candidate_startup_catchup"' not in source


def test_scheduler_refreshes_health_heartbeat_every_minute():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'scheduler.add_job(test_heartbeat, "interval", minutes=1' in source
