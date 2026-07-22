from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.jobs.startup_recovery import StartupRecovery


def test_startup_recovery_retries_failed_task_without_blocking_other_tasks():
    now = datetime(2026, 7, 18, 16, 1, tzinfo=ZoneInfo("Asia/Shanghai"))
    attempts = {"database_task": 0}

    def database_task():
        attempts["database_task"] += 1
        if attempts["database_task"] == 1:
            raise RuntimeError("database is not ready")
        return {"status": "ok"}

    recovery = StartupRecovery(
        {"database_task": database_task, "independent_task": lambda: {"status": "ok"}},
        retry_delays=(60, 120),
    )

    first = recovery.run(now)
    too_early = recovery.run(now + timedelta(seconds=30))
    retried = recovery.run(now + timedelta(seconds=60))

    assert first["completed"] == ["independent_task"]
    assert first["pending"] == ["database_task"]
    assert too_early["attempted"] == []
    assert retried["completed"] == ["database_task"]
    assert retried["pending"] == []
    assert attempts["database_task"] == 2


def test_startup_recovery_retries_error_results_and_never_duplicates_success():
    now = datetime(2026, 7, 18, 21, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    calls = {"task": 0}

    def task():
        calls["task"] += 1
        return {"status": "error" if calls["task"] == 1 else "ok"}

    recovery = StartupRecovery({"task": task}, retry_delays=(1,))

    assert recovery.run(now)["pending"] == ["task"]
    assert recovery.run(now + timedelta(seconds=1))["pending"] == []
    assert recovery.run(now + timedelta(seconds=2))["attempted"] == []
    assert calls["task"] == 2
