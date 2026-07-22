"""Codex multi-agent task orchestrator.

Production responsibilities:
- create agent_tasks
- assign owner_agent
- track state transitions
- enforce human review gates
- write audit logs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.agent_storage import (
    create_agent_task,
    create_review_gate,
    get_agent_task,
    has_pending_review_gate,
)
from scripts.agent_storage import (
    transition_task as _transition_task,
)
from scripts.business_time import utc_now_iso


@dataclass
class AgentTask:
    task_code: str
    task_title: str
    owner_agent: str
    task_type: str = "general"
    risk_level: str = "L2"
    status: str = "created"
    scope: str = ""
    input_refs: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: list[str] = field(default_factory=list)
    human_review_required: bool = False


def _now(value: datetime | None = None) -> str:
    return utc_now_iso(value)


def requires_human_review(task: AgentTask) -> bool:
    return task.risk_level in {"L4", "L5"} or task.human_review_required


def create_task(task: AgentTask) -> dict[str, Any]:
    """Create an agent task in the database."""
    task_dict = {
        "task_code": task.task_code,
        "task_title": task.task_title,
        "task_type": task.task_type,
        "owner_agent": task.owner_agent,
        "risk_level": task.risk_level,
        "status": task.status,
        "scope": task.scope,
        "input_refs": task.input_refs,
        "acceptance_criteria": task.acceptance_criteria,
        "human_review_required": requires_human_review(task),
        "created_by": "codex",
    }

    with get_db() as conn:
        tid = create_agent_task(conn, task_dict)
        if requires_human_review(task) and tid:
            create_review_gate(
                conn,
                {
                    "task_id": tid,
                    "gate_type": "human_review",
                    "reason": f"Risk level {task.risk_level} requires human review",
                },
            )

    return {
        "task_code": task.task_code,
        "task_id": tid,
        "status": task.status,
        "owner_agent": task.owner_agent,
        "human_review_required": requires_human_review(task),
        "created_at": _now(),
    }


def transition_task(task_code: str, new_status: str, summary: str = "") -> dict[str, Any]:
    """Transition a task to a new status with audit trail."""
    with get_db() as conn:
        if new_status in {"approved", "merged"}:
            task = get_agent_task(conn, task_code)
            if task and has_pending_review_gate(conn, task["id"]):
                raise PermissionError(f"Task {task_code} has a pending human review gate")
        ok = _transition_task(conn, task_code, new_status, summary)

    return {
        "task_code": task_code,
        "new_status": new_status,
        "success": ok,
        "summary": summary,
    }
