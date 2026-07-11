"""Task queue abstraction for scheduled AI and data jobs.

In local mode, this writes directly to PostgreSQL (ai_job_runs table).
No Redis/Celery dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.backend.src.db import get_db
from scripts.agent_storage import finish_job_run, retry_job_run, start_job_run


@dataclass
class JobEnvelope:
    job_code: str
    owner_agent: str
    payload: dict
    created_at: datetime
    priority: str = "medium"


def check_job_dependencies(job_codes: list[str]) -> None:
    """Require the latest local run of each dependency to be completed.

    An absent dependency or a latest run that is not completed blocks the new
    job before it writes a ``running`` record.
    """
    if not job_codes:
        return
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT DISTINCT ON (job_code) job_code, status
                   FROM ai_job_runs
                   WHERE job_code = ANY(%s)
                   ORDER BY job_code, created_at DESC, id DESC""",
                (job_codes,),
            )
            latest = {row[0]: row[1] for row in cur.fetchall()}
    blocked = [code for code in job_codes if latest.get(code) != "completed"]
    if blocked:
        raise RuntimeError("Job dependencies not completed: " + ", ".join(blocked))


def enqueue_job(job: JobEnvelope) -> int | None:
    """Start a job run in ai_job_runs. Returns the run_id."""
    with get_db() as conn:
        return start_job_run(
            conn,
            {
                "job_code": job.job_code,
                "job_name": job.job_code,  # code doubles as name for scheduled jobs
                "owner_agent": job.owner_agent,
                "schedule_type": "manual",
                "environment": "prod",
                "input_snapshot_refs": job.payload,
            },
        )


def start_tracked_job(
    job_code: str,
    owner_agent: str,
    input_refs: dict,
    dependencies: list[str] | None = None,
) -> int | None:
    """Start a local job run for a real scheduler/worker entrypoint."""
    dependency_list = dependencies or []
    check_job_dependencies(dependency_list)
    tracked_input_refs = dict(input_refs)
    if dependency_list:
        tracked_input_refs["dependencies"] = dependency_list
    with get_db() as conn:
        return start_job_run(conn, {
            "job_code": job_code,
            "job_name": job_code,
            "owner_agent": owner_agent,
            "schedule_type": "scheduled",
            "environment": "local",
            "input_snapshot_refs": tracked_input_refs,
        })


def finish_tracked_job(
    run_id: int | None,
    status: str,
    output_refs: dict | None = None,
    error: str | None = None,
) -> None:
    """Finish a tracked job without hiding a missing tracking id."""
    if run_id is None:
        return
    with get_db() as conn:
        finish_job_run(conn, run_id, status, output_refs=output_refs, error=error)


def retry_tracked_job(run_id: int, max_retries: int = 2) -> bool:
    """Retry a failed local job within its explicit retry budget."""
    with get_db() as conn:
        return retry_job_run(conn, run_id, max_retries=max_retries)


def mark_job_result(
    job_code: str,
    status: str,
    run_id: int | None = None,
    output_refs: dict | None = None,
    error: str | None = None,
) -> None:
    """Mark a job run as completed or failed."""
    if run_id is None:
        print(f"mark_job_result: {job_code} {status} (no run_id, skipping)")
        return

    with get_db() as conn:
        finish_job_run(conn, run_id, status, output_refs=output_refs, error=error)
