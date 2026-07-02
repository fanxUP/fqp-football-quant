"""Agent, task, job, and audit-log endpoints (Stage 7)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.agent_storage import (
    create_agent_task as _create_task,
)
from scripts.agent_storage import (
    list_agent_tasks as _list_tasks,
)
from scripts.agent_storage import (
    list_agents as _list_agents,
)
from scripts.agent_storage import (
    list_audit_logs as _list_logs,
)
from scripts.agent_storage import (
    list_job_runs as _list_jobs,
)
from scripts.agent_storage import (
    transition_task as _transition,
)

router = APIRouter(tags=["agents"])


@router.get("/api/agents")
def list_agents():
    """List agent definitions from the registry."""
    with get_db() as conn:
        agents = _list_agents(conn)
    return {"agents": agents, "total": len(agents)}


@router.get("/api/agent-tasks")
def list_agent_tasks(
    status: str | None = Query(None),
    owner_agent: str | None = Query(None),
    limit: int = Query(50),
):
    """List agent tasks, optionally filtered by status or owner."""
    with get_db() as conn:
        tasks = _list_tasks(conn, status=status, owner_agent=owner_agent, limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


@router.post("/api/agent-tasks")
def create_agent_task(body: dict):
    """Create a new agent task."""
    with get_db() as conn:
        tid = _create_task(conn, body)
    if not tid:
        return {"status": "error", "error": "failed to create task"}
    return {"status": "ok", "task_id": tid}


@router.post("/api/agent-tasks/{task_code}/transition")
def transition_agent_task(task_code: str, body: dict):
    """Transition an agent task to a new status."""
    with get_db() as conn:
        ok = _transition(
            conn,
            task_code,
            body.get("new_status", "completed"),
            body.get("summary", ""),
        )
    return {"status": "ok" if ok else "error", "task_code": task_code}


@router.get("/api/ai-jobs")
def list_ai_jobs(
    status: str | None = Query(None),
    job_code: str | None = Query(None),
    limit: int = Query(50),
):
    """List AI job runs, optionally filtered."""
    with get_db() as conn:
        jobs = _list_jobs(conn, status=status, job_code=job_code, limit=limit)
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/api/agent-audit-logs")
def list_agent_audit_logs(
    task_id: int | None = Query(None),
    agent_name: str | None = Query(None),
    limit: int = Query(50),
):
    """List agent audit log entries, optionally filtered."""
    with get_db() as conn:
        logs = _list_logs(conn, task_id=task_id, agent_name=agent_name, limit=limit)
    return {"logs": logs, "total": len(logs)}
