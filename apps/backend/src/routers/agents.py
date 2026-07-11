"""Agent, task, job, and audit-log endpoints (Stage 7)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.agent_storage import (
    create_agent_task as _create_task,
)
from scripts.local.scheduler_heartbeat import get_scheduler_status
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
    list_review_gates as _list_gates,
    get_agent_summary as _get_summary,
    list_stale_jobs as _list_stale_jobs,
    resolve_review_gate as _resolve_gate,
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


@router.get("/api/agent-review-gates")
def list_agent_review_gates(
    review_status: str | None = Query(None),
    limit: int = Query(50),
):
    """List human-review gates for Risk/QA monitoring."""
    with get_db() as conn:
        gates = _list_gates(conn, review_status=review_status, limit=limit)
    return {"gates": gates, "total": len(gates)}


@router.post("/api/agent-review-gates/{gate_id}/resolve")
def resolve_agent_review_gate(gate_id: int, body: dict):
    """Resolve a pending gate through an explicit human decision."""
    reviewer = str(body.get("reviewer", "")).strip()
    status = body.get("status")
    if not reviewer or status not in {"approved", "rejected"}:
        return {"status": "error", "error": "reviewer and approved/rejected status are required"}
    with get_db() as conn:
        updated = _resolve_gate(conn, gate_id, reviewer, status, body.get("comment", ""))
    return {"status": "ok" if updated else "error", "gate_id": gate_id, "review_status": status}


@router.get("/api/agent-summary")
def agent_summary():
    """Return counts for the Agent operations overview."""
    with get_db() as conn:
        summary = _get_summary(conn)
    return {"summary": summary}


@router.get("/api/agent-scheduler-status")
def agent_scheduler_status():
    """Return diagnostic information for the local Scheduler process."""
    return {"scheduler": get_scheduler_status()}


@router.get("/api/agent-stale-jobs")
def stale_agent_jobs(
    threshold_minutes: int = Query(30, ge=1),
    limit: int = Query(50, ge=1, le=200),
):
    """List running jobs exceeding the operational timeout threshold."""
    with get_db() as conn:
        jobs = _list_stale_jobs(conn, threshold_minutes=threshold_minutes, limit=limit)
    return {"jobs": jobs, "total": len(jobs), "threshold_minutes": threshold_minutes}
