"""Stage 7 storage layer: agent registry, tasks, audit logs, job runs.

Follows the same psycopg2 CRUD pattern as real_ticket_storage.py.
All functions accept conn: Any and call conn.commit() internally.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
    now_val = datetime.now()
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
