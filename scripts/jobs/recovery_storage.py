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


def promote_recovery_session(conn: Any, session_id: int, mode: str = "execute") -> bool:
    """Explicitly promote a planned session before real task execution."""
    if mode != "execute":
        raise ValueError("only execute promotion is supported")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE startup_recovery_sessions
               SET mode = 'execute'
               WHERE id = %s AND mode IN ('dry_run', 'plan')
               RETURNING id""",
            (session_id,),
        )
        promoted = cur.fetchone()
    conn.commit()
    return bool(promoted)


def claim_recovery_task(conn: Any, session_id: int) -> dict[str, Any] | None:
    """Atomically claim the next due task for a single executor."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, task_code, business_window_start, business_window_end,
                      strategy, attempt_count
               FROM startup_recovery_task_runs
               WHERE recovery_session_id = %s
                 AND status = 'planned'
                 AND (next_attempt_at IS NULL OR next_attempt_at <= NOW())
               ORDER BY id
               FOR UPDATE SKIP LOCKED
               LIMIT 1""",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """UPDATE startup_recovery_task_runs
               SET status = 'running', attempt_count = attempt_count + 1,
                   started_at = NOW(), next_attempt_at = NULL
               WHERE id = %s
               RETURNING id, task_code, business_window_start,
                         business_window_end, strategy, attempt_count""",
            (row[0],),
        )
        claimed = cur.fetchone()
    conn.commit()
    if not claimed:
        return None
    return {
        "id": claimed[0],
        "task_code": claimed[1],
        "business_window_start": claimed[2],
        "business_window_end": claimed[3],
        "strategy": claimed[4],
        "attempt_count": claimed[5],
    }


def finish_recovery_task(
    conn: Any,
    task_id: int,
    status: str,
    *,
    output_refs: dict | None = None,
    error: str | None = None,
    next_attempt_at: Any = None,
) -> bool:
    """Finish a claimed task or return it to the bounded retry queue."""
    if status not in TASK_STATUSES:
        raise ValueError(f"Unsupported recovery task status: {status}")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE startup_recovery_task_runs
               SET status = %s, finished_at = CASE
                       WHEN %s IN ('completed', 'failed', 'blocked') THEN NOW()
                       ELSE finished_at END,
                   error_message = %s,
                   next_attempt_at = %s,
                   output_refs = COALESCE(%s, output_refs)
               WHERE id = %s AND status = 'running'""",
            (
                status,
                status,
                error,
                next_attempt_at,
                json.dumps(output_refs, ensure_ascii=False) if output_refs is not None else None,
                task_id,
            ),
        )
        updated = cur.rowcount > 0
    conn.commit()
    return bool(updated)


def recovery_task_counts(conn: Any, session_id: int) -> dict[str, int]:
    """Return durable counts used to decide whether a session is complete."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT status, COUNT(*) FROM startup_recovery_task_runs
               WHERE recovery_session_id = %s GROUP BY status""",
            (session_id,),
        )
        rows = cur.fetchall()
    return {str(status): int(count) for status, count in rows}
