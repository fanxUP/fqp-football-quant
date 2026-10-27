"""Prediction ownership on the same PostgreSQL session that publishes outputs."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from apps.backend.src.db import get_pool
from scripts.model_prediction_run_storage import fail_prediction_run

EXECUTION_PROTOCOL = "prediction-session/v1"
_LOCK_KEY = (913201, 106)
_INTERRUPTED = "prediction execution session ended before completion"


def _recover_owned_runs(conn: Any) -> None:
    """Recover only versioned owners, atomically with their failed run manifests.

    Caller holds the prediction session lock. Unversioned history cannot prove
    ownership and is deliberately left for explicit reconciliation at cutover.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT j.id, j.status, j.error_message, r.id, r.run_status
                   FROM ai_job_runs j
                   LEFT JOIN model_prediction_runs r ON r.ai_job_run_id=j.id
                   WHERE j.job_code='model_prediction'
                     AND j.input_snapshot_refs->>'execution_protocol'=%s
                     AND (j.status='running' OR (j.status='failed' AND r.run_status='running'))
                   ORDER BY j.id FOR UPDATE OF j""",
                (EXECUTION_PROTOCOL,),
            )
            rows = cur.fetchall()
        for job_id, job_status, job_error, run_id, run_status in rows:
            if run_status == "running":
                reason = (
                    f"owning job already failed: {job_error or 'no recorded error'}"
                    if job_status == "failed"
                    else _INTERRUPTED
                )
                fail_prediction_run(conn, run_id, reason, commit=False)
            if job_status == "running":
                # A crash after finalizing the run must not relabel its output
                # as a failure merely because its audit acknowledgement is absent.
                status = "ok" if run_status in {"completed", "partial"} else "failed"
                with conn.cursor() as cur:
                    cur.execute(
                        """WITH recovery_clock AS MATERIALIZED
                             (SELECT clock_timestamp() AS recovered_at)
                           UPDATE ai_job_runs SET status=%s, finished_at=recovered_at,
                           duration_ms=CASE WHEN
                             EXTRACT(EPOCH FROM (recovered_at-started_at))*1000
                               BETWEEN 0 AND 2147483647
                             THEN FLOOR(EXTRACT(EPOCH FROM (recovered_at-started_at))*1000)::BIGINT
                             ELSE NULL END,
                           error_message=%s
                           FROM recovery_clock
                           WHERE id=%s AND status='running'""",
                        (status, None if status == "ok" else _INTERRUPTED, job_id),
                    )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@contextmanager
def prediction_execution() -> Iterator[Any | None]:
    """Yield an owned writing connection, or None if another execution owns it.

    Destroy the checked-out connection on every exit, including BaseException:
    returning a session lock to the pool would leave a ghost owner. The body
    must publish through this connection, so a lost lock session also fences its
    writes. Commit/rollback inside the body does not release a session lock.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(%s, %s)", _LOCK_KEY)
            acquired = cur.fetchone()[0]
        conn.commit()  # Do not hold an idle transaction during model computation.
        if not acquired:
            yield None
            return
        _recover_owned_runs(conn)
        yield conn
    finally:
        pool.putconn(conn, close=True)
