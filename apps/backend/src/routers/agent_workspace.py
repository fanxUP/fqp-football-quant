"""Authenticated, manual-only model workspace APIs."""

from __future__ import annotations

from time import perf_counter
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from apps.backend.src.db import get_db
from apps.backend.src.services.agent_workspace_store import (
    AgentWorkspaceError,
    create_workspace_task,
    delete_workspace_task,
    list_workspace_task_page,
    list_workspace_task_review_events,
    set_workspace_task_reviewed,
)
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import ProviderConfigError

router = APIRouter(prefix="/api/agent-workspace/tasks", tags=["agent-workspace"])


class WorkspaceTaskRequest(BaseModel):
    agentCode: str = Field(min_length=2, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=8000)

    @field_validator("title", "prompt")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("内容不能为空")
        return trimmed


class WorkspaceTaskReviewRequest(BaseModel):
    reviewed: bool
    reviewNote: str | None = Field(default=None, max_length=2000)

    @field_validator("reviewNote")
    @classmethod
    def normalize_review_note(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


@router.post("")
def create_task(body: WorkspaceTaskRequest):
    """Run exactly one manually requested analysis and archive its untrusted text result."""
    started_at = perf_counter()
    try:
        with get_db() as conn:
            result = invoke_agent_model(conn, body.agentCode, body.prompt)
            task = create_workspace_task(
                conn, title=body.title, agent_code=body.agentCode,
                provider_code=result.provider_code, model=result.model,
                prompt=body.prompt, response=result.content[:12000],
            )
            record_model_invocation(
                conn, agent_code=body.agentCode, provider_code=result.provider_code, model=result.model,
                status="succeeded", prompt_length=len(body.prompt), response_length=len(result.content),
                duration_ms=round((perf_counter() - started_at) * 1000),
            )
    except (ProviderConfigError, ModelGatewayError) as exc:
        with get_db() as conn:
            record_model_invocation(
                conn, agent_code=body.agentCode, provider_code=None, model=None, status="failed",
                prompt_length=len(body.prompt), response_length=0,
                duration_ms=round((perf_counter() - started_at) * 1000), error_code="MODEL_CALL_FAILED",
            )
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task": task}


@router.get("")
def get_tasks(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    review_status: Literal["all", "pending", "reviewed"] = Query("all", alias="reviewStatus"),
    query: str = Query("", alias="q", max_length=120),
):
    with get_db() as conn:
        tasks, total_items = list_workspace_task_page(
            conn, limit=limit, offset=offset, review_status=review_status, query=query.strip(),
        )
    # Keep `total` for existing clients; pagination is additive for new clients.
    return {
        "tasks": tasks,
        "total": len(tasks),
        "pagination": {
            "offset": offset,
            "limit": limit,
            "totalItems": total_items,
            "hasMore": offset + len(tasks) < total_items,
        },
    }


@router.patch("/{task_id}")
def update_task_review(task_id: int = Path(ge=1), body: WorkspaceTaskReviewRequest = ...):
    try:
        with get_db() as conn:
            task = set_workspace_task_reviewed(conn, task_id, body.reviewed, body.reviewNote)
    except AgentWorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task": task}


@router.get("/{task_id}/reviews")
def get_task_review_events(task_id: int = Path(ge=1), limit: int = Query(50, ge=1, le=100)):
    try:
        with get_db() as conn:
            events = list_workspace_task_review_events(conn, task_id, limit)
    except AgentWorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"events": events}


@router.delete("/{task_id}", status_code=204)
def remove_task(task_id: int = Path(ge=1)):
    try:
        with get_db() as conn:
            delete_workspace_task(conn, task_id)
    except AgentWorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
