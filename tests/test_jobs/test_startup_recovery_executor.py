from __future__ import annotations

import sys
import types
from unittest.mock import patch

from scripts.jobs.startup_recovery_executor import execute_recovery_task


def test_execute_recovery_task_dispatches_daily_review_window() -> None:
    task = {
        "id": 7,
        "task_code": "daily_review",
        "business_window_start": "2026-08-28T15:55:00+00:00",
    }
    fake_module = types.ModuleType("scripts.jobs.generate_daily_review")
    fake_run = patch.object(fake_module, "run", return_value={"status": "ok"}, create=True)
    with (
        patch.dict(sys.modules, {"scripts.jobs.generate_daily_review": fake_module}),
        fake_run as mocked_run,
    ):
        result = execute_recovery_task(task)

    assert result["status"] == "ok"
    mocked_run.assert_called_once_with(review_date="2026-08-28", dry_run=False)


def test_execute_recovery_task_rejects_unmapped_task() -> None:
    try:
        execute_recovery_task({"id": 1, "task_code": "unknown"})
    except ValueError as exc:
        assert "Unsupported recovery task" in str(exc)
    else:
        raise AssertionError("expected ValueError")
