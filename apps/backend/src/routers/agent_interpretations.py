"""Manual-only business interpretation endpoints, isolated from prediction and risk flows."""

from __future__ import annotations

from time import perf_counter
from typing import Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field, field_validator

from apps.backend.src.db import get_db
from apps.backend.src.services.agent_interpretation import (
    InterpretationSourceError, build_post_match_source, build_pre_match_source,
)
from apps.backend.src.services.agent_workspace_store import create_workspace_task
from apps.backend.src.services.model_gateway import ModelGatewayError, invoke_agent_model
from apps.backend.src.services.model_invocation_audit import record_model_invocation
from apps.backend.src.services.model_provider_store import ProviderConfigError

router = APIRouter(prefix="/api/agent-interpretations", tags=["agent-interpretations"])


class InterpretationRequest(BaseModel):
    focusQuestion: str | None = Field(default=None, max_length=2_000)

    @field_validator("focusQuestion")
    @classmethod
    def normalize_question(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None


def _run(source):
    started_at = perf_counter()
    try:
        with get_db() as conn:
            result = invoke_agent_model(conn, source.agent_code, source.prompt)
            task = create_workspace_task(
                conn, title=source.title, agent_code=source.agent_code, provider_code=result.provider_code,
                model=result.model, prompt=source.prompt, response=result.content[:12_000],
                source_type=source.source_type, source_ref=source.source_ref,
            )
            record_model_invocation(conn, agent_code=source.agent_code, provider_code=result.provider_code,
                model=result.model, status="succeeded", prompt_length=len(source.prompt),
                response_length=len(result.content), duration_ms=round((perf_counter() - started_at) * 1000))
        return {"task": task, "agentCode": source.agent_code, "providerCode": result.provider_code, "model": result.model}
    except (ProviderConfigError, ModelGatewayError) as exc:
        with get_db() as conn:
            record_model_invocation(conn, agent_code=source.agent_code, provider_code=None, model=None,
                status="failed", prompt_length=len(source.prompt), response_length=0,
                duration_ms=round((perf_counter() - started_at) * 1000), error_code="MODEL_CALL_FAILED")
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/pre-match/{match_id}")
def interpret_pre_match(match_id: int = Path(ge=1), body: InterpretationRequest = ...):
    try:
        with get_db() as conn:
            source = build_pre_match_source(conn, match_id, body.focusQuestion)
    except InterpretationSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run(source)


@router.post("/post-match/{source_type}/{source_ref}")
def interpret_post_match(
    source_type: Literal["post_daily", "post_weekly", "post_monthly"], source_ref: str,
    body: InterpretationRequest,
):
    try:
        with get_db() as conn:
            source = build_post_match_source(conn, source_type, source_ref, body.focusQuestion)
    except InterpretationSourceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _run(source)
