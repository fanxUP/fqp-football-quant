"""Real tickets, settlements, reviews, and error analysis endpoints (Stage 5)."""

from __future__ import annotations

import os
import re
import tempfile
from datetime import datetime as _dt
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from apps.backend.src.db import get_db
from scripts.ocr_ticket_parser import (
    process_ticket_image,
    result_to_dict,
)
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
    get_play_type_win_rate as _get_play_type_win_rate,
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

UPLOAD_ROOT = Path(os.getenv("FQP_UPLOAD_DIR", "data/uploads")).resolve()


def _safe_upload_name(filename: str | None) -> str:
    stem = Path(filename or "ticket.jpg").stem
    suffix = Path(filename or "ticket.jpg").suffix.lower() or ".jpg"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "ticket"
    timestamp = _dt.now().strftime("%Y%m%d%H%M%S%f")
    return f"{timestamp}_{safe_stem}{suffix}"


def _save_ticket_upload(filename: str | None, contents: bytes) -> tuple[Path, str]:
    ticket_dir = UPLOAD_ROOT / "tickets"
    ticket_dir.mkdir(parents=True, exist_ok=True)
    path = ticket_dir / _safe_upload_name(filename)
    path.write_bytes(contents)
    return path, f"/uploads/tickets/{path.name}"


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


@router.get("/api/reviews/play-type-winrate")
def get_play_type_winrate(days: int = Query(30)):
    """Get daily win-rate per play_type from settled real tickets.

    Returns a list of {settle_date, play_type, total, wins, win_rate}
    ordered by date ASC, suitable for a line chart.
    """
    with get_db() as conn:
        rows = _get_play_type_win_rate(conn, days=days)
    return {"status": "ok", "data": rows}


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


# ---------------------------------------------------------------------------
# OCR ticket upload (Phase 8)
# ---------------------------------------------------------------------------


@router.post("/api/real-tickets/upload")
@router.post("/api/tickets/ocr")
def ocr_ticket_image(file: UploadFile = File(...)):  # noqa: B008
    """上传实票照片，OCR 识别并返回结构化数据。

    支持格式：PNG、JPG、JPEG、WEBP（最大10MB）。
    返回识别结果供用户确认后正式录入。
    """
    # 校验文件类型
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if file.content_type and file.content_type not in allowed_types:
        raise HTTPException(400, f"不支持的文件类型: {file.content_type}。支持: PNG, JPG, WEBP")

    # 校验文件大小
    contents = file.file.read()
    max_size = 10 * 1024 * 1024  # 10MB
    if len(contents) > max_size:
        raise HTTPException(400, f"文件过大 ({len(contents) / 1024 / 1024:.1f}MB)，最大 10MB")

    _, ticket_image_url = _save_ticket_upload(file.filename, contents)

    suffix = os.path.splitext(file.filename or "ticket.jpg")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(contents)
        tmp_path = tmp.name

    try:
        result = process_ticket_image(tmp_path, engine="auto")
        response = result_to_dict(result)
        response["filename"] = file.filename
        response["size_bytes"] = len(contents)
        response["ticket_image_url"] = ticket_image_url
        return response
    except RuntimeError as e:
        raise HTTPException(500, f"OCR 处理失败: {e}") from e
    finally:
        # 清理临时文件
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@router.post("/api/real-tickets/{ticket_id}/confirm")
def confirm_real_ticket(ticket_id: int, body: dict | None = None):
    """Confirm a real ticket after OCR/manual correction."""
    updates = {"confirm_status": "confirmed"}
    if body:
        updates.update(body)
    with get_db() as conn:
        ok = _update_ticket(conn, ticket_id, updates)
    return {"status": "ok" if ok else "not_found", "ticket_id": ticket_id}


@router.post("/api/real-tickets/{ticket_id}/settle")
def settle_real_ticket(ticket_id: int, body: dict | None = None):
    """Mark a real ticket settlement status from an external settlement job/manual review."""
    status = (body or {}).get("settlement_status", "settled")
    with get_db() as conn:
        ok = _update_ticket(conn, ticket_id, {"settlement_status": status})
    return {"status": "ok" if ok else "not_found", "ticket_id": ticket_id}
