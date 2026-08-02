"""Authenticated, manual-only model workspace APIs."""

from __future__ import annotations

from time import perf_counter
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator

from apps.backend.src.db import get_db
from apps.backend.src.services.agent_workspace_store import (
    AgentWorkspaceError,
    create_workspace_comparison,
    create_workspace_task,
    delete_workspace_task,
    get_workspace_comparison,
    list_workspace_comparison_tasks,
    list_workspace_task_page,
    list_workspace_task_review_events,
    set_workspace_comparison_completed,
    set_workspace_comparison_reviewed,
    set_workspace_task_reviewed,
)
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import AGENT_MODEL_OPTIONS, ProviderConfigError

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


class WorkspaceComparisonRequest(WorkspaceTaskRequest):
    target_agent_codes: list[str] = Field(alias="targetAgentCodes", max_length=3)

    @field_validator("target_agent_codes")
    @classmethod
    def require_distinct_targets(cls, value: list[str]) -> list[str]:
        if len(value) < 2:
            raise ValueError("至少选择两个已启用模型")
        if len(set(value)) != len(value):
            raise ValueError("对比模型不能重复")
        if any(agent_code not in AGENT_MODEL_OPTIONS for agent_code in value):
            raise ValueError("包含不支持的智能代理")
        return value


class WorkspaceComparisonReviewRequest(BaseModel):
    reviewNote: str = Field(min_length=1, max_length=2000)

    @field_validator("reviewNote")
    @classmethod
    def normalize_review_note(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("人工结论不能为空")
        return trimmed


def _run_workspace_task(
    *, agent_code: str, title: str, prompt: str, comparison_id: str | None = None,
) -> dict:
    started_at = perf_counter()
    try:
        with get_db() as conn:
            result = invoke_agent_model(conn, agent_code, prompt)
            task = create_workspace_task(
                conn, title=title, agent_code=agent_code,
                provider_code=result.provider_code, model=result.model,
                prompt=prompt, response=result.content[:12000], comparison_id=comparison_id,
            )
            record_model_invocation(
                conn, agent_code=agent_code, provider_code=result.provider_code, model=result.model,
                status="succeeded", prompt_length=len(prompt), response_length=len(result.content),
                duration_ms=round((perf_counter() - started_at) * 1000),
            )
            return task
    except (ProviderConfigError, ModelGatewayError):
        with get_db() as conn:
            record_model_invocation(
                conn, agent_code=agent_code, provider_code=None, model=None, status="failed",
                prompt_length=len(prompt), response_length=0,
                duration_ms=round((perf_counter() - started_at) * 1000), error_code="MODEL_CALL_FAILED",
            )
        raise


@router.post("")
def create_task(body: WorkspaceTaskRequest):
    """Run exactly one manually requested analysis and archive its untrusted text result."""
    try:
        task = _run_workspace_task(agent_code=body.agentCode, title=body.title, prompt=body.prompt)
    except (ProviderConfigError, ModelGatewayError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task": task}


@router.post("/comparisons")
def create_comparison(body: WorkspaceComparisonRequest):
    """Run up to three manual, independently auditable analyses of the same material."""
    comparison_id = str(uuid4())
    tasks: list[dict] = []
    failures: list[dict[str, str]] = []
    with get_db() as conn:
        create_workspace_comparison(conn, comparison_id, body.target_agent_codes)
    try:
        for agent_code in body.target_agent_codes:
            try:
                tasks.append(_run_workspace_task(
                    agent_code=agent_code, title=body.title, prompt=body.prompt, comparison_id=comparison_id,
                ))
            except (ProviderConfigError, ModelGatewayError) as exc:
                failures.append({"agentCode": agent_code, "message": str(exc)})
    finally:
        with get_db() as conn:
            comparison = set_workspace_comparison_completed(
                conn, comparison_id, succeeded_count=len(tasks), failed_count=len(failures),
            )
    return {"comparisonId": comparison_id, "comparison": comparison, "tasks": tasks, "failures": failures}


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


@router.get("/comparisons/{comparison_id}")
def get_comparison_tasks(comparison_id: UUID):
    """Read archived outputs from one manually initiated comparison batch."""
    with get_db() as conn:
        comparison = get_workspace_comparison(conn, str(comparison_id))
        tasks = list_workspace_comparison_tasks(conn, str(comparison_id))
    return {"comparisonId": str(comparison_id), "comparison": comparison, "tasks": tasks}


@router.patch("/comparisons/{comparison_id}")
def update_comparison_review(comparison_id: UUID, body: WorkspaceComparisonReviewRequest):
    try:
        with get_db() as conn:
            comparison = set_workspace_comparison_reviewed(conn, str(comparison_id), body.reviewNote)
    except AgentWorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"comparison": comparison}


@router.patch("/{task_id}")
def update_task_review(
    body: Annotated[WorkspaceTaskReviewRequest, Body()], task_id: int = Path(ge=1),
):
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
