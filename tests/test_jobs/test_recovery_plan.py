from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from scripts.jobs.recovery_plan import build_recovery_plan

TZ = ZoneInfo("Asia/Shanghai")


def test_latest_only_task_is_planned_once_for_a_long_gap() -> None:
    outage_start = datetime(2026, 8, 28, 21, 30, tzinfo=TZ)
    outage_end = datetime(2026, 8, 29, 12, 30, tzinfo=TZ)

    plan = build_recovery_plan(
        outage_start,
        outage_end,
        {"official_schedule": outage_start - timedelta(hours=1)},
    )

    task = next(item for item in plan if item["task_code"] == "official_schedule")
    assert task["strategy"] == "latest_only"
    assert task["windows"] == [None]
    assert task["execute"] is True


def test_each_window_task_preserves_missing_business_windows() -> None:
    outage_start = datetime(2026, 8, 27, 23, 0, tzinfo=TZ)
    outage_end = datetime(2026, 8, 29, 1, 0, tzinfo=TZ)

    plan = build_recovery_plan(
        outage_start,
        outage_end,
        {"daily_review": outage_start - timedelta(days=1)},
    )

    task = next(item for item in plan if item["task_code"] == "daily_review")
    assert task["strategy"] == "each_window"
    assert len(task["windows"]) == 2
    assert all(window.tzinfo is not None for window in task["windows"])


def test_unrecoverable_time_series_is_marked_not_executed() -> None:
    outage_start = datetime(2026, 8, 28, 21, 30, tzinfo=TZ)
    outage_end = datetime(2026, 8, 29, 12, 30, tzinfo=TZ)

    plan = build_recovery_plan(outage_start, outage_end, {"minute_odds": outage_start})

    task = next(item for item in plan if item["task_code"] == "minute_odds")
    assert task["strategy"] == "mark_gap"
    assert task["execute"] is False
    assert task["gap"] == {"start": outage_start, "end": outage_end}


def test_recent_success_does_not_create_a_duplicate_latest_only_run() -> None:
    outage_start = datetime(2026, 8, 29, 11, 0, tzinfo=TZ)
    outage_end = datetime(2026, 8, 29, 12, 0, tzinfo=TZ)

    plan = build_recovery_plan(
        outage_start,
        outage_end,
        {"official_schedule": outage_end - timedelta(minutes=5)},
    )

    task = next(item for item in plan if item["task_code"] == "official_schedule")
    assert task["execute"] is False
    assert task["reason"] == "already_fresh"
