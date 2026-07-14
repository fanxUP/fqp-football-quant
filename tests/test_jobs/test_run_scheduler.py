from datetime import datetime, timedelta

from scripts.jobs.run_scheduler import (
    OFFICIAL_SCHEDULE_CRON,
    _audited_job,
    _business_now,
    _scheduler_timezone_name,
    _should_run_recommendation_catchup,
)


def test_self_tracked_job_is_not_wrapped_again():
    def job():
        return "tracked"

    wrapped = _audited_job("run_model_prediction", "模型预测", "model_agent", job)
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


def test_scheduler_refreshes_official_schedule_metadata_every_30_minutes():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert OFFICIAL_SCHEDULE_CRON == {"minute": "10,40"}
    assert "**OFFICIAL_SCHEDULE_CRON" in source


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


def test_scheduler_registers_startup_recommendation_catchup():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'id="run_recommendation_candidate_startup_catchup"' in source
    assert "run_date=_business_now(timezone_name)" in source


def test_scheduler_refreshes_health_heartbeat_every_minute():
    from pathlib import Path

    source = Path("scripts/jobs/run_scheduler.py").read_text()
    assert 'scheduler.add_job(test_heartbeat, "interval", minutes=1' in source
