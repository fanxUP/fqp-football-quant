"""Controlled configuration resource for optional automatic report interpretation."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from apps.backend.src.db import get_db
from apps.backend.src.services.agent_workspace_store import get_workspace_task_for_source
from apps.backend.src.services.report_automation import (
    POST_MATCH_REPORT_AGENT,
    get_post_match_report_automation,
    set_post_match_report_automation,
)

router = APIRouter(prefix="/api/report-automation", tags=["report-automation"])


class ReportAutomationUpdateRequest(BaseModel):
    enabled: bool


@router.get("")
def get_report_automation():
    with get_db() as conn:
        return {"automation": get_post_match_report_automation(conn)}


@router.put("")
def put_report_automation(body: ReportAutomationUpdateRequest):
    try:
        with get_db() as conn:
            automation = set_post_match_report_automation(conn, body.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"automation": automation}


@router.get("/archive/{source_type}/{source_ref}")
def get_report_automation_archive(
    source_type: Literal["post_daily", "post_weekly", "post_monthly"],
    source_ref: str = Path(min_length=1, max_length=64),
):
    """Return only the dedicated automatic report archived for this fixed source."""
    with get_db() as conn:
        task = get_workspace_task_for_source(
            conn,
            agent_code=POST_MATCH_REPORT_AGENT,
            source_type=source_type,
            source_ref=source_ref,
        )
    return {"task": task}
