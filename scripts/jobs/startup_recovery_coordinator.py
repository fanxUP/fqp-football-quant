"""Plan startup recovery from the last durable health boundary.

Phase 2 persists a bounded, idempotent plan. Execution is intentionally gated
behind a later production drill and is not performed by this coordinator.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.jobs.recovery_plan import DEFAULT_POLICIES, build_recovery_plan
from scripts.jobs.recovery_storage import (
    create_recovery_session,
    insert_recovery_task_plan,
    mark_recovery_session,
)

TASK_JOB_CODES = {
    "official_schedule": ("crawl_official_schedule",),
    "current_odds": ("crawl_official_odds", "run_official_odds_snapshot"),
    "build_feature_snapshots": ("build_feature_snapshots",),
    "run_model_prediction": ("run_model_prediction",),
    "run_recommendation_candidate": ("run_recommendation_candidate",),
    "daily_review": ("generate_daily_review",),
    "settle_tickets": ("settle_tickets",),
}


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return f"pid-{os.getpid()}"


def _aware(value: Any) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _last_health_snapshot(conn: Any) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT MAX(snapshot_time) FROM operational_health_snapshots")
        row = cur.fetchone()
    return _aware(row[0]) if row and row[0] else None


def _last_success_by_task(conn: Any) -> dict[str, datetime | None]:
    result: dict[str, datetime | None] = {}
    with conn.cursor() as cur:
        for task_code, job_codes in TASK_JOB_CODES.items():
            cur.execute(
                """SELECT MAX(finished_at) FROM ai_job_runs
                   WHERE status IN ('completed', 'ok', 'success')
                     AND job_code = ANY(%s)""",
                (list(job_codes),),
            )
            row = cur.fetchone()
            result[task_code] = _aware(row[0]) if row and row[0] else None
    return result


def _window_value(value: Any) -> str:
    return value.isoformat() if hasattr(value, "isoformat") else "latest"


def _task_rows(session_id: int, plan: list[dict], outage_end: datetime) -> list[dict]:
    rows: list[dict] = []
    for item in plan:
        windows = item.get("windows") or [None]
        for window in windows:
            window_start = window if hasattr(window, "isoformat") else None
            key = f"{session_id}:{item['task_code']}:{_window_value(window)}"
            rows.append(
                {
                    "task_code": item["task_code"],
                    "strategy": item["strategy"],
                    "business_window_start": window_start,
                    "business_window_end": outage_end if window_start else None,
                    "idempotency_key": key,
                    "status": "planned" if item.get("execute") else "skipped",
                    "output_refs": {"reason": item.get("reason", "")},
                }
            )
    return rows


def run_startup_recovery_plan(now: datetime | None = None, mode: str | None = None) -> dict[str, Any]:
    """Persist one startup plan; return ``blocked`` when no safe boundary exists."""
    current = _require_aware(now, "now") if now is not None else datetime.now(UTC)
    selected_mode = mode or os.getenv("FQP_STARTUP_RECOVERY_MODE", "plan").lower()
    if selected_mode not in {"dry_run", "plan", "execute"}:
        return {"status": "blocked", "reason": "invalid_mode", "mode": selected_mode}

    with get_db() as conn:
        boundary = _last_health_snapshot(conn)
        if boundary is None:
            return {"status": "blocked", "reason": "no_health_boundary", "mode": selected_mode}
        if current <= boundary:
            return {"status": "no_gap", "mode": selected_mode, "last_health_snapshot": boundary.isoformat()}
        if current - boundary < timedelta(minutes=30):
            return {"status": "no_gap", "mode": selected_mode, "last_health_snapshot": boundary.isoformat()}

        session = create_recovery_session(
            conn,
            boot_id=_boot_id(),
            outage_start=boundary,
            outage_end=current,
            mode=selected_mode,
        )
        plan = build_recovery_plan(boundary, current, _last_success_by_task(conn), DEFAULT_POLICIES)
        rows = _task_rows(session["id"], plan, current)
        inserted = sum(insert_recovery_task_plan(conn, session["id"], row) for row in rows)
        summary = {
            "outage_start": boundary.isoformat(),
            "outage_end": current.isoformat(),
            "task_count": len(rows),
            "inserted_task_count": inserted,
            "executable_task_count": sum(row["status"] == "planned" for row in rows),
            "mode": selected_mode,
        }
        mark_recovery_session(conn, session["id"], "planned", summary)
    return {"status": "planned", "session_id": session["id"], **summary}
