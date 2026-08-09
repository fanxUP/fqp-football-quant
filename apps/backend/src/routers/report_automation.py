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

_SOURCE_REPORT_TYPES = {
    "post_daily": "daily",
    "post_weekly": "weekly",
    "post_monthly": "monthly",
}


class ReportAutomationUpdateRequest(BaseModel):
    enabled: bool


def get_report_snapshot_for_source(
    conn, *, source_type: Literal["post_daily", "post_weekly", "post_monthly"], source_ref: str
) -> dict | None:
    """Expose the small immutable report summary needed by the report page.

    Match cards and stored prompts are intentionally excluded: the detail UI
    receives only confirmed aggregate facts and research-quality metrics.
    """
    report_type = _SOURCE_REPORT_TYPES[source_type]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT source_snapshot_json
            FROM report_generation_runs
            WHERE report_type = %s AND period_key = %s AND status = 'completed'
            """,
            (report_type, source_ref),
        )
        row = cur.fetchone()
    if not row or not isinstance(row[0], dict):
        return None
    snapshot = row[0]
    report = {
        "sourceType": source_type,
        "sourceRef": source_ref,
        "schemaVersion": snapshot.get("schemaVersion", 1),
        "researchMetrics": snapshot.get("researchMetrics"),
        "upsetReport": snapshot.get("upsetReport"),
    }
    if source_type == "post_daily":
        report["dailyReview"] = snapshot.get("dailyReview")
    else:
        report["aggregate"] = snapshot.get("aggregate")
        report["dailyReportRefs"] = snapshot.get("dailyReportRefs", [])
    return report


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


@router.get("/snapshot/{source_type}/{source_ref}")
def get_report_automation_snapshot(
    source_type: Literal["post_daily", "post_weekly", "post_monthly"],
    source_ref: str = Path(min_length=1, max_length=64),
):
    with get_db() as conn:
        report = get_report_snapshot_for_source(
            conn,
            source_type=source_type,
            source_ref=source_ref,
        )
    return {"report": report}
