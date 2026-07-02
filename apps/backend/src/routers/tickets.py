"""Real tickets, settlements, reviews, and error analysis endpoints (Stage 5)."""

from __future__ import annotations

from datetime import datetime as _dt

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.real_ticket_storage import (
    create_real_ticket as _create_ticket,
)
from scripts.real_ticket_storage import (
    create_real_ticket_items_batch,
    get_error_summary,
    get_settlement_summary,
    get_settlements_by_date,
    list_real_ticket_items,
)
from scripts.real_ticket_storage import (
    delete_real_ticket as _delete_ticket,
)
from scripts.real_ticket_storage import (
    get_daily_review as _get_daily_review,
)
from scripts.real_ticket_storage import (
    get_real_ticket as _get_ticket,
)
from scripts.real_ticket_storage import (
    list_daily_reviews as _list_daily_reviews,
)
from scripts.real_ticket_storage import (
    list_error_analyses as _list_error_analyses,
)
from scripts.real_ticket_storage import (
    list_monthly_reviews as _list_monthly_reviews,
)
from scripts.real_ticket_storage import (
    list_real_tickets as _list_tickets,
)
from scripts.real_ticket_storage import (
    list_weekly_reviews as _list_weekly_reviews,
)
from scripts.real_ticket_storage import (
    update_real_ticket as _update_ticket,
)

router = APIRouter(tags=["tickets"])


@router.get("/api/real-tickets")
def list_real_tickets(
    status: str | None = Query(None),
    limit: int = Query(20),
):
    """List real tickets, optionally filtered by settlement_status."""
    with get_db() as conn:
        tickets = _list_tickets(conn, status=status, limit=limit)
    return {"tickets": tickets, "total": len(tickets)}


@router.post("/api/real-tickets")
def create_real_ticket(body: dict):
    """Create a real ticket with items. Manual entry (no OCR).

    Body: {"ticket": {...}, "items": [{...}, ...]}
    """
    with get_db() as conn:
        ticket_id = _create_ticket(conn, body.get("ticket", {}))
        if not ticket_id:
            return {"status": "error", "error": "failed to create ticket"}
        item_ids = create_real_ticket_items_batch(conn, ticket_id, body.get("items", []))
    return {"status": "ok", "ticket_id": ticket_id, "item_count": len(item_ids)}


@router.get("/api/real-tickets/{ticket_id}")
def get_real_ticket(ticket_id: int):
    """Get a single real ticket with its items."""
    with get_db() as conn:
        ticket = _get_ticket(conn, ticket_id)
        if not ticket:
            return {"status": "error", "error": "not found"}
        items = list_real_ticket_items(conn, ticket_id)
    return {"ticket": ticket, "items": items}


@router.put("/api/real-tickets/{ticket_id}")
def update_real_ticket(ticket_id: int, body: dict):
    """Update a real ticket (link to simulation, change status, etc.)."""
    with get_db() as conn:
        ok = _update_ticket(conn, ticket_id, body)
    return {"status": "ok" if ok else "error"}


@router.delete("/api/real-tickets/{ticket_id}")
def delete_real_ticket(ticket_id: int):
    """Delete a real ticket and its items."""
    with get_db() as conn:
        ok = _delete_ticket(conn, ticket_id)
    return {"status": "ok" if ok else "error"}


@router.get("/api/settlements")
def list_settlements(
    date: str | None = Query(None),
    source: str | None = Query(None),
    limit: int = Query(50),
):
    """List ticket settlements, optionally filtered by date and source."""
    with get_db() as conn:
        d = date or _dt.now().strftime("%Y-%m-%d")
        settlements = get_settlements_by_date(conn, d, source)
    return {"settlements": settlements, "total": len(settlements)}


@router.get("/api/settlements/summary")
def settlement_summary(date: str = Query(...)):
    """Get settlement summary for a specific date."""
    with get_db() as conn:
        summary = get_settlement_summary(conn, date)
    return summary


@router.get("/api/reviews/daily")
def list_daily_reviews(limit: int = Query(30)):
    """List daily reviews, newest first."""
    with get_db() as conn:
        reviews = _list_daily_reviews(conn, limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


@router.get("/api/reviews/daily/{date}")
def get_daily_review(date: str):
    """Get a specific daily review by date (YYYY-MM-DD)."""
    with get_db() as conn:
        review = _get_daily_review(conn, date)
    if not review:
        return {"status": "not_found"}
    return review


@router.get("/api/reviews/weekly")
def list_weekly_reviews(limit: int = Query(12)):
    """List weekly reviews, newest first."""
    with get_db() as conn:
        reviews = _list_weekly_reviews(conn, limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


@router.get("/api/reviews/monthly")
def list_monthly_reviews(limit: int = Query(12)):
    """List monthly reviews, newest first."""
    with get_db() as conn:
        reviews = _list_monthly_reviews(conn, limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


@router.get("/api/error-analysis")
def list_error_analyses(
    match_id: int | None = Query(None),
    error_type: str | None = Query(None),
    limit: int = Query(50),
):
    """List prediction error analyses, optionally filtered."""
    with get_db() as conn:
        errors = _list_error_analyses(conn, match_id=match_id, error_type=error_type, limit=limit)
    return {"errors": errors, "total": len(errors)}


@router.get("/api/error-analysis/summary")
def error_analysis_summary(days: int = Query(7)):
    """Get error type distribution for recent days."""
    with get_db() as conn:
        summary = get_error_summary(conn, days=days)
    return summary
