"""Backtest session ownership and recovery of explicitly linked executions."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from psycopg2.extras import Json

from apps.backend.src.db import get_pool

EXECUTION_PROTOCOL = "backtest-session/v1"
_LOCK_KEY = (913201, 107)
_INTERRUPTED = "backtest execution session ended before completion"


def _reconcile_job(
    conn: Any,
    job_id: int,
    *,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Caller owns the write session; no commit until parent/children agree."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT status, input_snapshot_refs, error_message FROM ai_job_runs
               WHERE id=%s AND job_code='backtest'
                 AND input_snapshot_refs->>'execution_protocol'=%s FOR UPDATE""",
            (job_id, EXECUTION_PROTOCOL),
        )
        job = cur.fetchone()
        if job is None:
            raise RuntimeError("backtest audit owner is missing or unversioned")
        job_status, refs, recorded_error = job
        cur.execute(
            "SELECT id, status FROM backtest_runs WHERE ai_job_run_id=%s ORDER BY id FOR UPDATE",
            (job_id,),
        )
        children = cur.fetchall()
        reason = (error or recorded_error or _INTERRUPTED)[:1000]
        for run_id, status in children:
            if status == "running":
                cur.execute(
                    """UPDATE backtest_runs SET status='failed', error_message=%s,
                           finished_at=clock_timestamp() WHERE id=%s AND status='running'""",
                    (reason, run_id),
                )
        # A completed subset of a sweep is not proof the whole sweep finished.
        expected = refs.get("expected_runs")
        complete = (
            type(expected) is int
            and expected > 0
            and len(children) == expected
            and all(status == "completed" for _, status in children)
        )
        dry_run = result is not None and result.get("status") == "dry_run" and expected == 0
        status = "ok" if complete else "dry_run" if dry_run else "failed"
        if job_status == "running":
            cur.execute(
                """WITH recovery_clock AS MATERIALIZED
                     (SELECT clock_timestamp() AS recovered_at)
                   UPDATE ai_job_runs SET status=%s, finished_at=recovered_at,
                     duration_ms=CASE WHEN
                       EXTRACT(EPOCH FROM (recovered_at-started_at))*1000 BETWEEN 0 AND 2147483647
                       THEN FLOOR(EXTRACT(EPOCH FROM (recovered_at-started_at))*1000)::BIGINT
                       ELSE NULL END,
                     error_message=%s, output_refs=%s
                   FROM recovery_clock WHERE id=%s AND status='running'""",
                (
                    status,
                    reason if status == "failed" else None,
                    Json({"result": result})
                    if result is not None
                    else Json({"reconciled": True, "linked_runs": len(children)}),
                    job_id,
                ),
            )


def reconcile_backtest_job(
    conn: Any, job_id: int, *, result: dict | None = None, error: str | None = None
) -> None:
    try:
        _reconcile_job(conn, job_id, result=result, error=error)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _recover_owned_runs(conn: Any) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT j.id FROM ai_job_runs j
                   WHERE j.job_code='backtest'
                     AND j.input_snapshot_refs->>'execution_protocol'=%s
                     AND (j.status='running' OR (j.status='failed' AND EXISTS (
                       SELECT 1 FROM backtest_runs r
                       WHERE r.ai_job_run_id=j.id AND r.status='running')))
                   ORDER BY j.id FOR UPDATE OF j""",
                (EXECUTION_PROTOCOL,),
            )
            ids = [row[0] for row in cur.fetchall()]
        for job_id in ids:
            _reconcile_job(conn, job_id)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@contextmanager
def backtest_execution() -> Iterator[Any | None]:
    """Use this same connection for the audit, linkage and every output write."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", _LOCK_KEY)
            acquired = cur.fetchone()[0]
        conn.commit()
        if not acquired:
            yield None
            return
        _recover_owned_runs(conn)
        yield conn
    finally:
        pool.putconn(conn, close=True)
