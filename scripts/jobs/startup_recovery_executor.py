"""Bounded executor for the durable startup recovery plan."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.jobs.recovery_storage import (
    claim_recovery_task,
    finish_recovery_task,
    mark_recovery_session,
    recovery_task_counts,
)

MAX_ATTEMPTS = 2
RETRY_DELAY = timedelta(minutes=5)


def _business_date(value: Any) -> str:
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    elif isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    from zoneinfo import ZoneInfo

    return parsed.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()


def execute_recovery_task(task: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one task using its normal idempotent job entrypoint."""
    code = str(task.get("task_code", ""))
    if code == "official_schedule":
        from scripts.jobs.crawl_official_schedule import run

        return run()
    if code == "current_odds":
        from scripts.jobs.run_official_odds_snapshot import run

        return run(dry_run=False)
    if code == "build_feature_snapshots":
        from scripts.jobs.run_feature_snapshot_build import run

        return run(dry_run=False)
    if code == "run_model_prediction":
        from scripts.jobs.run_model_prediction import run

        return run(dry_run=False)
    if code == "run_recommendation_candidate":
        from scripts.jobs.run_recommendation_candidate import run

        return run(dry_run=False)
    if code == "daily_review":
        from scripts.jobs.generate_daily_review import run

        return run(review_date=_business_date(task.get("business_window_start")), dry_run=False)
    if code == "settle_tickets":
        from scripts.jobs.settle_tickets import run

        return run(dry_run=False)
    raise ValueError(f"Unsupported recovery task: {code}")


def execute_recovery_session(session_id: int, max_tasks: int = 200) -> dict[str, Any]:
    """Execute due tasks with row locking and finite retry semantics."""
    processed = 0
    completed = 0
    failed = 0
    with get_db() as conn:
        while processed < max_tasks:
            task = claim_recovery_task(conn, session_id)
            if task is None:
                break
            processed += 1
            try:
                result = execute_recovery_task(task)
                status = str(result.get("status", "ok")).lower() if isinstance(result, dict) else "ok"
                if status in {"error", "failed", "blocked"}:
                    raise RuntimeError(str(result.get("error") or result.get("message") or result))
                finish_recovery_task(conn, task["id"], "completed", output_refs={"result": result})
                completed += 1
            except Exception as exc:  # noqa: BLE001 - persist and bound job failures
                retry = int(task.get("attempt_count", 1)) < MAX_ATTEMPTS
                finish_recovery_task(
                    conn,
                    task["id"],
                    "planned" if retry else "failed",
                    error=str(exc)[:1000],
                    next_attempt_at=(datetime.now(UTC) + RETRY_DELAY) if retry else None,
                )
                failed += 1

        counts = recovery_task_counts(conn, session_id)
        pending = counts.get("planned", 0) + counts.get("running", 0)
        if pending == 0 and counts.get("failed", 0) == 0:
            session_status = "completed"
        elif counts.get("failed", 0) > 0:
            session_status = "failed"
        else:
            session_status = "planned"
        mark_recovery_session(
            conn,
            session_id,
            session_status,
            {
                "processed": processed,
                "completed": completed,
                "failed_attempts": failed,
                "task_counts": counts,
            },
        )
    return {
        "status": (
            "completed"
            if session_status == "completed"
            else "recovering"
            if session_status == "planned"
            else "failed"
        ),
        "session_id": session_id,
        "processed": processed,
        "completed": completed,
        "failed_attempts": failed,
        "pending": pending,
        "task_counts": counts,
    }
