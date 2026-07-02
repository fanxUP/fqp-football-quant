"""Task queue abstraction for scheduled AI and data jobs.

In local mode, this writes directly to PostgreSQL (ai_job_runs table).
No Redis/Celery dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.backend.src.db import get_db
from scripts.agent_storage import finish_job_run, start_job_run


@dataclass
class JobEnvelope:
    job_code: str
    owner_agent: str
    payload: dict
    created_at: datetime
    priority: str = "medium"


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
