"""Cold-result research overview and traceable event endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from apps.backend.src.db import get_db
from scripts.upset.queries import get_upset_detail, get_upset_summary, list_upsets

router = APIRouter(prefix="/api/upsets", tags=["upsets"])


@router.get("/summary")
def summary(start_date: str | None = None, end_date: str | None = None):
    with get_db() as conn:
        return get_upset_summary(conn, start_date=start_date, end_date=end_date)


@router.get("")
def index(
    start_date: str | None = None,
    end_date: str | None = None,
    level: str | None = None,
    play_type: str | None = None,
    user_involved: bool | None = None,
    agent_involved: bool | None = None,
    review_status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    with get_db() as conn:
        items, total = list_upsets(
            conn,
            start_date=start_date,
            end_date=end_date,
            level=level,
            play_type=play_type,
            user_involved=user_involved,
            agent_involved=agent_involved,
            review_status=review_status,
            limit=limit,
            offset=offset,
        )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{event_id}")
def detail(event_id: int):
    with get_db() as conn:
        payload = get_upset_detail(conn, event_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="冷门事件不存在")
    return payload
