"""Controlled configuration resource for optional automatic report interpretation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from apps.backend.src.db import get_db
from apps.backend.src.services.report_automation import (
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
