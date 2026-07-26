from unittest.mock import patch

from scripts import official_crawler_stub


def test_worker_cycle_uses_tracked_odds_job_and_publishes_heartbeat(monkeypatch):
    monkeypatch.setenv("OFFICIAL_SOURCE_ENABLED", "true")
    monkeypatch.setenv("FQP_ODDS_DISPATCH_OWNER", "worker")
    expected = {"status": "ok", "matches_due": 0, "snapshots_inserted": 0}

    with (
        patch("scripts.official_crawler_stub.write_worker_heartbeat") as heartbeat,
        patch("scripts.jobs.run_official_odds_snapshot.run", return_value=expected) as run,
    ):
        result = official_crawler_stub.run_once()

    assert result == expected
    run.assert_called_once_with()
    assert heartbeat.call_count == 2


def test_disabled_worker_still_publishes_liveness_without_dispatch(monkeypatch):
    monkeypatch.setenv("OFFICIAL_SOURCE_ENABLED", "false")
    monkeypatch.setenv("FQP_ODDS_DISPATCH_OWNER", "worker")

    with (
        patch("scripts.official_crawler_stub.write_worker_heartbeat") as heartbeat,
        patch("scripts.jobs.run_official_odds_snapshot.run") as run,
    ):
        result = official_crawler_stub.run_once()

    assert result == {"status": "skipped", "reason": "official_source_disabled"}
    heartbeat.assert_called_once_with()
    run.assert_not_called()


def test_worker_stays_idle_when_scheduler_owns_dispatch(monkeypatch):
    monkeypatch.setenv("OFFICIAL_SOURCE_ENABLED", "true")
    monkeypatch.setenv("FQP_ODDS_DISPATCH_OWNER", "scheduler")

    with (
        patch("scripts.official_crawler_stub.write_worker_heartbeat") as heartbeat,
        patch("scripts.jobs.run_official_odds_snapshot.run") as run,
    ):
        result = official_crawler_stub.run_once()

    assert result == {"status": "skipped", "reason": "scheduler_owns_odds_dispatch"}
    heartbeat.assert_called_once_with()
    run.assert_not_called()
