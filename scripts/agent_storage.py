"""Stage 7 storage layer: agent registry, tasks, audit logs, job runs.

Follows the same psycopg2 CRUD pattern as real_ticket_storage.py.
All functions accept conn: Any and call conn.commit() internally.
"""

from __future__ import annotations

import json
from typing import Any

from scripts.business_time import utc_now_naive

TASK_STATUSES = {
    "created",
    "queued",
    "assigned",
    "running",
    "in_progress",
    "waiting_review",
    "blocked",
    "failed",
    "passed_tests",
    "approved",
    "rejected",
    "merged",
    "closed",
    "completed",
    "cancelled",
}


# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------


def seed_agent_registry(conn: Any, agents: list[dict]) -> int:
    """Idempotent seed of agent_registry from YAML config. Returns count inserted."""
    sql = """
        INSERT INTO agent_registry (agent_name, agent_type, description,
                                    permission_level, is_active, created_at, updated_at)
        VALUES (%(agent_name)s, %(agent_type)s, %(description)s,
                %(permission_level)s, true, now(), now())
        ON CONFLICT (agent_name) DO NOTHING
    """
    count = 0
    with conn.cursor() as cur:
        for a in agents:
            cur.execute(
                sql,
                {
                    "agent_name": a.get("name", ""),
                    "agent_type": a.get("type", ""),
                    "description": a.get("description", ""),
                    "permission_level": a.get("permission_level", "P2"),
                },
            )
            if cur.rowcount and cur.rowcount > 0:
                count += 1
    conn.commit()
    return count


def list_agents(conn: Any, is_active: bool = True) -> list[dict]:
    """List agent definitions, optionally filtered by active status."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, agent_name, agent_type, description, permission_level,
                   is_active, created_at
            FROM agent_registry
            WHERE is_active = %(is_active)s
            ORDER BY agent_name
            """,
            {"is_active": is_active},
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "agent_name": r[1],
            "agent_type": r[2],
            "description": r[3],
            "permission_level": r[4],
            "is_active": r[5],
            "created_at": r[6].isoformat() if hasattr(r[6], "isoformat") else str(r[6]),
        }
        for r in rows
    ]


def get_agent(conn: Any, agent_name: str) -> dict | None:
    """Get a single agent definition by name."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, agent_name, agent_type, description, permission_level, is_active FROM agent_registry WHERE agent_name = %s",
            (agent_name,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "agent_name": row[1],
        "agent_type": row[2],
        "description": row[3],
        "permission_level": row[4],
        "is_active": row[5],
    }


# ---------------------------------------------------------------------------
# Agent tasks
# ---------------------------------------------------------------------------


def create_agent_task(conn: Any, task: dict) -> int | None:
    """Create an agent task. Returns the new task id."""
    sql = """
        INSERT INTO agent_tasks (
            task_code, task_title, task_type, owner_agent, priority, risk_level,
            status, scope, input_refs, acceptance_criteria,
            human_review_required, created_by, assigned_at, created_at, updated_at
        ) VALUES (
            %(task_code)s, %(task_title)s, %(task_type)s, %(owner_agent)s,
            %(priority)s, %(risk_level)s, %(status)s, %(scope)s,
            %(input_refs)s, %(acceptance_criteria)s,
            %(human_review_required)s, %(created_by)s, now(), now(), now()
        )
        RETURNING id
    """
    params = {
        "task_code": task["task_code"],
        "task_title": task.get("task_title", ""),
        "task_type": task.get("task_type", "general"),
        "owner_agent": task.get("owner_agent", ""),
        "priority": task.get("priority", "medium"),
        "risk_level": task.get("risk_level", "L2"),
        "status": task.get("status", "created"),
        "scope": task.get("scope", ""),
        "input_refs": json.dumps(task.get("input_refs", {}), ensure_ascii=False),
        "acceptance_criteria": json.dumps(task.get("acceptance_criteria", []), ensure_ascii=False),
        "human_review_required": task.get("human_review_required", False),
        "created_by": task.get("created_by", "codex"),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def transition_task(conn: Any, task_code: str, new_status: str, summary: str = "") -> bool:
    """Update task status and write audit log. Returns True on success."""
    if new_status not in TASK_STATUSES:
        raise ValueError(f"Unsupported task status: {new_status}")
    now_val = utc_now_naive()
    sql = """
        UPDATE agent_tasks
        SET status = %(new_status)s,
            updated_at = %(now)s,
            started_at = CASE WHEN %(new_status)s = 'in_progress' THEN %(now)s ELSE started_at END,
            finished_at = CASE WHEN %(new_status)s IN ('completed', 'failed', 'cancelled') THEN %(now)s ELSE finished_at END
        WHERE task_code = %(task_code)s
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "task_code": task_code,
                "new_status": new_status,
                "now": now_val,
            },
        )
        row = cur.fetchone()
    if not row:
        conn.commit()
        return False

    task_id = row[0]

    # Write audit log
    write_audit_log(
        conn,
        {
            "task_id": task_id,
            "agent_name": "orchestrator",
            "action_type": "transition",
            "result_status": new_status,
            "result_summary": summary,
        },
    )

    conn.commit()
    return True


def add_task_artifact(conn: Any, artifact: dict) -> int | None:
    """Register a task output with its path, digest, summary, and metadata."""
    sql = """
        INSERT INTO agent_task_artifacts (
            task_id, artifact_type, artifact_path, artifact_summary,
            artifact_hash, metadata, created_at
        ) VALUES (%(task_id)s, %(artifact_type)s, %(artifact_path)s,
                  %(artifact_summary)s, %(artifact_hash)s, %(metadata)s, now())
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "task_id": artifact["task_id"],
                "artifact_type": artifact.get("artifact_type", "output"),
                "artifact_path": artifact.get("artifact_path"),
                "artifact_summary": artifact.get("artifact_summary", ""),
                "artifact_hash": artifact.get("artifact_hash"),
                "metadata": json.dumps(artifact.get("metadata", {}), ensure_ascii=False),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def list_task_artifacts(conn: Any, task_id: int, limit: int = 100) -> list[dict]:
    """List registered artifacts for one task."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, task_id, artifact_type, artifact_path, artifact_summary,
                      artifact_hash, metadata, created_at
               FROM agent_task_artifacts
               WHERE task_id = %s ORDER BY created_at DESC LIMIT %s""",
            (task_id, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "task_id": r[1],
            "artifact_type": r[2],
            "artifact_path": r[3],
            "artifact_summary": r[4],
            "artifact_hash": r[5],
            "metadata": r[6],
            "created_at": r[7].isoformat() if hasattr(r[7], "isoformat") else str(r[7]),
        }
        for r in rows
    ]


def list_agent_tasks(
    conn: Any,
    status: str | None = None,
    owner_agent: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List agent tasks, optionally filtered."""
    clauses = []
    params: dict = {"limit": limit}
    if status:
        clauses.append("status = %(status)s")
        params["status"] = status
    if owner_agent:
        clauses.append("owner_agent = %(owner_agent)s")
        params["owner_agent"] = owner_agent
    where = " AND ".join(clauses) if clauses else "TRUE"

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, task_code, task_title, task_type, owner_agent,
                   priority, risk_level, status, scope,
                   human_review_required, created_by, assigned_at,
                   started_at, finished_at, created_at, updated_at
            FROM agent_tasks
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()

    def _ts(v: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return [
        {
            "id": r[0],
            "task_code": r[1],
            "task_title": r[2],
            "task_type": r[3],
            "owner_agent": r[4],
            "priority": r[5],
            "risk_level": r[6],
            "status": r[7],
            "scope": r[8],
            "human_review_required": r[9],
            "created_by": r[10],
            "assigned_at": _ts(r[11]),
            "started_at": _ts(r[12]),
            "finished_at": _ts(r[13]),
            "created_at": _ts(r[14]),
            "updated_at": _ts(r[15]),
        }
        for r in rows
    ]


def get_agent_task(conn: Any, task_code: str) -> dict | None:
    """Get a single agent task by task_code."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, task_code, task_title, task_type, owner_agent,
                   priority, risk_level, status, scope,
                   input_refs, acceptance_criteria,
                   human_review_required, created_by,
                   started_at, finished_at, created_at, updated_at
            FROM agent_tasks
            WHERE task_code = %s
            """,
            (task_code,),
        )
        row = cur.fetchone()
    if not row:
        return None

    def _ts(v: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return {
        "id": row[0],
        "task_code": row[1],
        "task_title": row[2],
        "task_type": row[3],
        "owner_agent": row[4],
        "priority": row[5],
        "risk_level": row[6],
        "status": row[7],
        "scope": row[8],
        "input_refs": row[9],
        "acceptance_criteria": row[10],
        "human_review_required": row[11],
        "created_by": row[12],
        "started_at": _ts(row[13]),
        "finished_at": _ts(row[14]),
        "created_at": _ts(row[15]),
        "updated_at": _ts(row[16]),
    }


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------


def write_audit_log(conn: Any, entry: dict) -> int | None:
    """Write an agent audit log entry. Returns the new log id."""
    sql = """
        INSERT INTO agent_audit_logs (
            task_id, agent_name, action_type, command_text,
            files_changed, tables_touched, environment,
            risk_level, result_status, result_summary, created_at
        ) VALUES (
            %(task_id)s, %(agent_name)s, %(action_type)s, %(command_text)s,
            %(files_changed)s, %(tables_touched)s, %(environment)s,
            %(risk_level)s, %(result_status)s, %(result_summary)s, now()
        )
        RETURNING id
    """
    params = {
        "task_id": entry.get("task_id"),
        "agent_name": entry.get("agent_name", ""),
        "action_type": entry.get("action_type", ""),
        "command_text": entry.get("command_text"),
        "files_changed": json.dumps(entry.get("files_changed", []))
        if entry.get("files_changed")
        else None,
        "tables_touched": json.dumps(entry.get("tables_touched", []))
        if entry.get("tables_touched")
        else None,
        "environment": entry.get("environment", "local"),
        "risk_level": entry.get("risk_level", "L2"),
        "result_status": entry.get("result_status", ""),
        "result_summary": entry.get("result_summary", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def list_audit_logs(
    conn: Any,
    task_id: int | None = None,
    agent_name: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List agent audit log entries, optionally filtered."""
    clauses = []
    params: dict = {"limit": limit}
    if task_id is not None:
        clauses.append("task_id = %(task_id)s")
        params["task_id"] = task_id
    if agent_name:
        clauses.append("agent_name = %(agent_name)s")
        params["agent_name"] = agent_name
    where = " AND ".join(clauses) if clauses else "TRUE"

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, task_id, agent_name, action_type, command_text,
                   result_status, result_summary, created_at
            FROM agent_audit_logs
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()

    def _ts(v: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return [
        {
            "id": r[0],
            "task_id": r[1],
            "agent_name": r[2],
            "action_type": r[3],
            "command_text": r[4],
            "result_status": r[5],
            "result_summary": r[6],
            "created_at": _ts(r[7]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# AI job runs
# ---------------------------------------------------------------------------


def start_job_run(conn: Any, job: dict) -> int | None:
    """Insert a new ai_job_run and return its id."""
    sql = """
        INSERT INTO ai_job_runs (
            job_code, job_name, owner_agent, schedule_type, environment,
            input_snapshot_refs, status, started_at, created_at
        ) VALUES (
            %(job_code)s, %(job_name)s, %(owner_agent)s, %(schedule_type)s,
            %(environment)s, %(input_snapshot_refs)s, 'running', now(), now()
        )
        RETURNING id
    """
    params = {
        "job_code": job.get("job_code", ""),
        "job_name": job.get("job_name", ""),
        "owner_agent": job.get("owner_agent", ""),
        "schedule_type": job.get("schedule_type", "cron"),
        "environment": job.get("environment", "prod"),
        "input_snapshot_refs": json.dumps(job.get("input_snapshot_refs", {}))
        if job.get("input_snapshot_refs")
        else None,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def finish_job_run(
    conn: Any,
    run_id: int,
    status: str,
    output_refs: dict | None = None,
    error: str | None = None,
) -> bool:
    """Mark an ai_job_run as completed/failed. Returns True on success."""
    sql = """
        UPDATE ai_job_runs
        SET status = %(status)s,
            output_refs = %(output_refs)s,
            error_message = %(error)s,
            finished_at = now(),
            duration_ms = EXTRACT(EPOCH FROM (now() - started_at)) * 1000
        WHERE id = %(run_id)s
    """
    params = {
        "run_id": run_id,
        "status": status,
        "output_refs": json.dumps(output_refs, ensure_ascii=False) if output_refs else None,
        "error": error,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
    conn.commit()
    return True


def recover_interrupted_job_runs(
    conn: Any,
    job_codes: list[str],
    reason: str = "owning process restarted before completion",
) -> int:
    """Fail unfinished runs that belong to a restarting single-owner process."""
    owned_codes = list(dict.fromkeys(code for code in job_codes if code))
    if not owned_codes:
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ai_job_runs
               SET status = 'failed', finished_at = now(),
                   duration_ms = EXTRACT(EPOCH FROM (now() - started_at)) * 1000,
                   error_message = %s
               WHERE status = 'running' AND job_code = ANY(%s)
               """,
            (reason, owned_codes),
        )
        recovered = cur.rowcount
    conn.commit()
    return int(recovered or 0)


def retry_job_run(conn: Any, run_id: int, max_retries: int = 2) -> bool:
    """Restart a failed job run when its retry budget has not been exhausted.

    Retries reuse the same run record so the execution history remains
    append-only at the audit/job level while ``retry_count`` is explicit.
    Only failed runs may be retried.
    """
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ai_job_runs
               SET status = 'running', retry_count = retry_count + 1,
                   started_at = now(), finished_at = NULL,
                   duration_ms = NULL, error_message = NULL
               WHERE id = %s AND status = 'failed' AND retry_count < %s
               RETURNING id""",
            (run_id, max_retries),
        )
        row = cur.fetchone()
    conn.commit()
    return bool(row)


def list_job_runs(
    conn: Any,
    status: str | None = None,
    job_code: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """List AI job runs, optionally filtered."""
    clauses = []
    params: dict = {"limit": limit}
    if status:
        clauses.append("status = %(status)s")
        params["status"] = status
    if job_code:
        clauses.append("job_code = %(job_code)s")
        params["job_code"] = job_code
    where = " AND ".join(clauses) if clauses else "TRUE"

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, job_code, job_name, owner_agent, schedule_type,
                   environment, status, retry_count, started_at,
                   finished_at, duration_ms, error_message, created_at
            FROM ai_job_runs
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()

    def _ts(v: Any) -> str | None:
        if v is None:
            return None
        return v.isoformat() if hasattr(v, "isoformat") else str(v)

    return [
        {
            "id": r[0],
            "job_code": r[1],
            "job_name": r[2],
            "owner_agent": r[3],
            "schedule_type": r[4],
            "environment": r[5],
            "status": r[6],
            "retry_count": r[7],
            "started_at": _ts(r[8]),
            "finished_at": _ts(r[9]),
            "duration_ms": r[10],
            "error_message": r[11],
            "created_at": _ts(r[12]),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Human review gates
# ---------------------------------------------------------------------------


def create_review_gate(conn: Any, gate: dict) -> int | None:
    """Create a human review gate for a task. Returns the new gate id."""
    sql = """
        INSERT INTO agent_human_review_gates (
            task_id, gate_type, reason, review_status, created_at
        ) VALUES (
            %(task_id)s, %(gate_type)s, %(reason)s, 'pending', now()
        )
        RETURNING id
    """
    params = {
        "task_id": gate.get("task_id"),
        "gate_type": gate.get("gate_type", "manual"),
        "reason": gate.get("reason", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def has_pending_review_gate(conn: Any, task_id: int) -> bool:
    """Return whether a task still has an unresolved human-review gate."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT EXISTS(
                   SELECT 1 FROM agent_human_review_gates
                   WHERE task_id = %s AND review_status = 'pending'
               )""",
            (task_id,),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def resolve_review_gate(
    conn: Any, gate_id: int, reviewer: str, status: str, comment: str = ""
) -> bool:
    """Resolve a review gate with an explicit reviewer and decision."""
    if status not in {"approved", "rejected"}:
        raise ValueError("review status must be approved or rejected")
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE agent_human_review_gates
               SET review_status = %s, reviewer = %s, review_comment = %s,
                   reviewed_at = now()
               WHERE id = %s AND review_status = 'pending'
               RETURNING id""",
            (status, reviewer, comment, gate_id),
        )
        row = cur.fetchone()
    conn.commit()
    return bool(row)


def list_review_gates(conn: Any, review_status: str | None = None, limit: int = 50) -> list[dict]:
    """List human-review gates with their owning task context."""
    clause = "AND g.review_status = %(review_status)s" if review_status else ""
    params: dict[str, Any] = {"limit": limit}
    if review_status:
        params["review_status"] = review_status
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT g.id, g.task_id, t.task_code, t.task_title,
                       g.gate_type, g.reason, g.reviewer, g.review_status,
                       g.review_comment, g.reviewed_at, g.created_at
                FROM agent_human_review_gates g
                JOIN agent_tasks t ON t.id = g.task_id
                WHERE TRUE {clause}
                ORDER BY g.created_at DESC LIMIT %(limit)s""",
            params,
        )
        rows = cur.fetchall()

    def ts(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)

    return [
        {
            "id": r[0],
            "task_id": r[1],
            "task_code": r[2],
            "task_title": r[3],
            "gate_type": r[4],
            "reason": r[5],
            "reviewer": r[6],
            "review_status": r[7],
            "review_comment": r[8],
            "reviewed_at": ts(r[9]),
            "created_at": ts(r[10]),
        }
        for r in rows
    ]


def get_agent_summary(conn: Any) -> dict[str, int | bool]:
    """Return compact counts for the local Agent operations overview."""
    queries = {
        "active_agents": "SELECT COUNT(*) FROM agent_registry WHERE is_active = true",
        "open_tasks": """SELECT COUNT(*) FROM agent_tasks
                          WHERE status NOT IN ('completed', 'closed', 'cancelled')""",
        "running_jobs": "SELECT COUNT(*) FROM ai_job_runs WHERE status = 'running'",
        "stale_jobs": """SELECT COUNT(*) FROM ai_job_runs
                         WHERE status = 'running' AND started_at < now() - interval '30 minutes'""",
        "stale_tasks": """SELECT COUNT(*) FROM agent_tasks
                          WHERE status IN ('running', 'in_progress')
                            AND COALESCE(updated_at, started_at, assigned_at, created_at)
                                < now() - interval '60 minutes'""",
        "failed_jobs_24h": """SELECT COUNT(*) FROM ai_job_runs
                              WHERE status = 'failed' AND created_at >= now() - interval '24 hours'""",
        "pending_review_gates": """SELECT COUNT(*) FROM agent_human_review_gates
                                  WHERE review_status = 'pending'""",
    }
    result: dict[str, int] = {}
    with conn.cursor() as cur:
        for key, sql in queries.items():
            cur.execute(sql)
            row = cur.fetchone()
            result[key] = int(row[0] or 0) if row else 0
    from scripts.local.scheduler_heartbeat import is_scheduler_alive

    result["scheduler_running"] = is_scheduler_alive()
    return result


def list_stale_jobs(conn: Any, threshold_minutes: int = 30, limit: int = 50) -> list[dict]:
    """List running jobs older than the operational timeout threshold."""
    if threshold_minutes < 1:
        raise ValueError("threshold_minutes must be positive")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, job_code, job_name, owner_agent, started_at,
                      EXTRACT(EPOCH FROM (now() - started_at)) / 60,
                      input_snapshot_refs
               FROM ai_job_runs
               WHERE status = 'running'
                 AND started_at < now() - (%s * interval '1 minute')
               ORDER BY started_at ASC LIMIT %s""",
            (threshold_minutes, limit),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "job_code": r[1],
            "job_name": r[2],
            "owner_agent": r[3],
            "started_at": r[4].isoformat() if hasattr(r[4], "isoformat") else str(r[4]),
            "running_minutes": round(float(r[5] or 0), 1),
            "input_refs": r[6],
        }
        for r in rows
    ]


def list_stale_tasks(conn: Any, threshold_minutes: int = 60, limit: int = 50) -> list[dict]:
    """List active Agent tasks with no progress update before the timeout."""
    if threshold_minutes < 1:
        raise ValueError("threshold_minutes must be positive")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id, task_code, task_title, owner_agent, status,
                      started_at, updated_at,
                      EXTRACT(EPOCH FROM (
                          now() - COALESCE(updated_at, started_at, assigned_at, created_at)
                      )) / 60
               FROM agent_tasks
               WHERE status IN ('running', 'in_progress')
                 AND COALESCE(updated_at, started_at, assigned_at, created_at)
                     < now() - (%s * interval '1 minute')
               ORDER BY COALESCE(updated_at, started_at, assigned_at, created_at) ASC
               LIMIT %s""",
            (threshold_minutes, limit),
        )
        rows = cur.fetchall()

    def ts(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)

    return [
        {
            "id": r[0],
            "task_code": r[1],
            "task_title": r[2],
            "owner_agent": r[3],
            "status": r[4],
            "started_at": ts(r[5]),
            "updated_at": ts(r[6]),
            "stale_minutes": round(float(r[7] or 0), 1),
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Codex review reports
# ---------------------------------------------------------------------------


def create_review_report(conn: Any, report: dict) -> int | None:
    """Create a codex review report. Returns the new report id."""
    sql = """
        INSERT INTO codex_review_reports (
            task_id, report_type, test_command,
            pass_count, fail_count, coverage, report_json, created_at
        ) VALUES (
            %(task_id)s, %(report_type)s, %(test_command)s,
            %(pass_count)s, %(fail_count)s, %(coverage)s,
            %(report_json)s, now()
        )
        RETURNING id
    """
    params = {
        "task_id": report.get("task_id"),
        "report_type": report.get("report_type", "qa"),
        "test_command": report.get("test_command"),
        "pass_count": report.get("pass_count", 0),
        "fail_count": report.get("fail_count", 0),
        "coverage": report.get("coverage"),
        "report_json": json.dumps(report.get("report_json", {}))
        if report.get("report_json")
        else None,
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None
