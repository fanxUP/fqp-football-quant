"""Durable storage for startup recovery sessions and task plans."""

from __future__ import annotations

import json
from typing import Any

SESSION_STATUSES = {"planned", "running", "completed", "failed", "blocked"}
TASK_STATUSES = {"planned", "skipped", "running", "completed", "failed", "blocked"}


def create_recovery_session(
    conn: Any,
    *,
    boot_id: str,
    outage_start: Any,
    outage_end: Any,
    mode: str,
) -> dict[str, Any]:
    """Create one session per boot and return its stable id/status."""
    if not boot_id or len(boot_id) > 128:
        raise ValueError("boot_id must be between 1 and 128 characters")
    if mode not in {"dry_run", "plan", "execute"}:
        raise ValueError(f"unsupported recovery mode: {mode}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO startup_recovery_sessions
                (boot_id, outage_start, outage_end, mode, status)
            VALUES (%(boot_id)s, %(outage_start)s, %(outage_end)s, %(mode)s, 'planned')
            ON CONFLICT (boot_id) DO NOTHING
            RETURNING id, status
            """,
            {
                "boot_id": boot_id,
                "outage_start": outage_start,
                "outage_end": outage_end,
                "mode": mode,
            },
        )
        row = cur.fetchone()
        if not row:
            cur.execute(
                """SELECT id, status FROM startup_recovery_sessions WHERE boot_id = %s""",
                (boot_id,),
            )
            row = cur.fetchone()
    conn.commit()
    if not row:
        raise RuntimeError("recovery session could not be created or loaded")
    return {"id": int(row[0]), "status": str(row[1])}


def insert_recovery_task_plan(conn: Any, recovery_session_id: int, task: dict[str, Any]) -> bool:
    """Insert one planned task; repeated keys are harmless no-ops."""
    status = str(task.get("status", "planned"))
    if status not in TASK_STATUSES:
        raise ValueError(f"Unsupported recovery task status: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO startup_recovery_task_runs (
                recovery_session_id, task_code, business_window_start,
                business_window_end, idempotency_key, strategy, status,
                next_attempt_at, output_refs
            ) VALUES (
                %(recovery_session_id)s, %(task_code)s, %(business_window_start)s,
                %(business_window_end)s, %(idempotency_key)s, %(strategy)s,
                %(status)s, %(next_attempt_at)s, %(output_refs)s
            )
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            {
                "recovery_session_id": recovery_session_id,
                "task_code": str(task["task_code"]),
                "business_window_start": task.get("business_window_start"),
                "business_window_end": task.get("business_window_end"),
                "idempotency_key": str(task["idempotency_key"]),
                "strategy": str(task.get("strategy", "latest_only")),
                "status": status,
                "next_attempt_at": task.get("next_attempt_at"),
                "output_refs": json.dumps(task.get("output_refs", {}), ensure_ascii=False),
            },
        )
        inserted = cur.rowcount > 0
    conn.commit()
    return bool(inserted)


def mark_recovery_session(conn: Any, session_id: int, status: str, summary: dict | None = None) -> bool:
    """Update a recovery session status with an auditable summary."""
    if status not in SESSION_STATUSES:
        raise ValueError(f"Unsupported recovery session status: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE startup_recovery_sessions
            SET status = %s,
                summary = COALESCE(%s, summary),
                finished_at = CASE WHEN %s IN ('completed', 'failed', 'blocked') THEN NOW() ELSE finished_at END
            WHERE id = %s
            """,
            (
                status,
                json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                status,
                session_id,
            ),
        )
        updated = cur.rowcount > 0
    conn.commit()
    return bool(updated)
