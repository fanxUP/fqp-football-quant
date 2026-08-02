"""Historical, manual ticket entry using archived official Sporttery odds."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.backend.src.db import get_db
from apps.backend.src.services.time_machine_betting import build_time_machine_matches
from scripts.business_time import business_today
from scripts.real_ticket_storage import create_real_ticket, create_real_ticket_items_batch
from scripts.simulator_calculator import calculate_multi_all, parse_pass_types, validate_items

router = APIRouter(tags=["time-machine"])


class TimeMachineSelectionRequest(BaseModel):
    match_id: int = Field(gt=0)
    play_type: str = Field(min_length=1, max_length=32)
    option_code: str = Field(min_length=1, max_length=64)


class CreateTimeMachineTicketRequest(BaseModel):
    business_date: date
    pass_type: str = Field(min_length=1, max_length=128)
    multiple: int = Field(1, ge=1, le=50)
    selections: list[TimeMachineSelectionRequest] = Field(min_length=1, max_length=40)
    ticket_no: str | None = Field(None, max_length=128)
    notes: str = Field("", max_length=1000)


def _require_historical_date(business_date: date) -> None:
    if business_date >= business_today():
        raise HTTPException(status_code=422, detail="时光机仅支持已结束的历史业务日")


def _calculate(items: list[dict], pass_type: str, multiple: int) -> dict:
    pass_types = parse_pass_types(pass_type)
    errors = [error for item_pass_type in pass_types for error in validate_items(items, item_pass_type)]
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})
    try:
        return calculate_multi_all(items, pass_types, multiple)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/betting/time-machine/dates")
def list_time_machine_dates(limit: int = Query(180, ge=1, le=365)):
    """List historical business dates with official pre-close odds evidence."""
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.business_date, COUNT(DISTINCT m.id)
            FROM official_matches m
            WHERE m.business_date < %(today)s
              AND m.official_match_code IS NOT NULL
              AND COALESCE(m.sale_stop_time, m.kickoff_time) <= timezone('Asia/Shanghai', NOW())
              AND EXISTS (
                  SELECT 1 FROM official_odds_snapshots o
                  WHERE o.match_id = m.id
                    AND o.is_open = TRUE
                    AND o.snapshot_time <= COALESCE(m.sale_stop_time, m.kickoff_time)
              )
            GROUP BY m.business_date
            ORDER BY m.business_date DESC
            LIMIT %(limit)s
            """,
            {"today": business_today(), "limit": limit},
        )
        rows = cur.fetchall()
    return {
        "dates": [
            {"businessDate": row[0].isoformat(), "matchCount": int(row[1])}
            for row in rows
        ]
    }


@router.get("/api/betting/time-machine/matches")
def list_time_machine_matches(business_date: date = Query(...)):
    """Return official historical matches and their last pre-close odds."""
    _require_historical_date(business_date)
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.official_match_code, m.league_name,
                   m.home_team_name, m.away_team_name, m.kickoff_time,
                   m.sale_stop_time, m.raw_json
            FROM official_matches m
            WHERE m.business_date = %(business_date)s
              AND m.official_match_code IS NOT NULL
              AND COALESCE(m.sale_stop_time, m.kickoff_time) <= timezone('Asia/Shanghai', NOW())
            ORDER BY m.kickoff_time, m.id
            """,
            {"business_date": business_date},
        )
        match_rows = cur.fetchall()
        if not match_rows:
            return {"businessDate": business_date.isoformat(), "matches": [], "total": 0}
        match_ids = [int(row[0]) for row in match_rows]
        cur.execute(
            """
            SELECT o.match_id, o.id, o.snapshot_time, o.play_type,
                   o.option_code, o.option_name, o.sp_value, o.handicap,
                   o.is_single_allowed
            FROM official_odds_snapshots o
            JOIN official_matches m ON m.id = o.match_id
            WHERE o.match_id = ANY(%(match_ids)s)
              AND o.is_open = TRUE
              AND o.snapshot_time <= COALESCE(m.sale_stop_time, m.kickoff_time)
            ORDER BY o.match_id, o.play_type, o.option_code, o.snapshot_time DESC, o.id DESC
            """,
            {"match_ids": match_ids},
        )
        odds_rows = cur.fetchall()
    matches = build_time_machine_matches(match_rows, odds_rows)
    return {"businessDate": business_date.isoformat(), "matches": matches, "total": len(matches)}


def _resolve_selections(conn, request: CreateTimeMachineTicketRequest) -> list[dict]:
    seen: set[tuple[int, str, str]] = set()
    resolved: list[dict] = []
    with conn.cursor() as cur:
        for selection in request.selections:
            selection_key = (selection.match_id, selection.play_type, selection.option_code)
            if selection_key in seen:
                raise HTTPException(status_code=422, detail="不允许重复选择同一玩法选项")
            seen.add(selection_key)
            cur.execute(
                """
                SELECT m.id, m.official_match_code, o.id, o.snapshot_time,
                       o.play_type, o.option_code, o.option_name, o.sp_value,
                       o.handicap, o.is_single_allowed
                FROM official_matches m
                JOIN LATERAL (
                    SELECT snapshot.id, snapshot.snapshot_time, snapshot.play_type,
                           snapshot.option_code, snapshot.option_name, snapshot.sp_value,
                           snapshot.handicap, snapshot.is_single_allowed
                    FROM official_odds_snapshots snapshot
                    WHERE snapshot.match_id = m.id
                      AND snapshot.play_type = %(play_type)s
                      AND snapshot.option_code = %(option_code)s
                      AND snapshot.is_open = TRUE
                      AND snapshot.snapshot_time <= COALESCE(m.sale_stop_time, m.kickoff_time)
                    ORDER BY snapshot.snapshot_time DESC, snapshot.id DESC
                    LIMIT 1
                ) o ON TRUE
                WHERE m.id = %(match_id)s
                  AND m.business_date = %(business_date)s
                  AND m.official_match_code IS NOT NULL
                  AND COALESCE(m.sale_stop_time, m.kickoff_time) <= timezone('Asia/Shanghai', NOW())
                """,
                {
                    "match_id": selection.match_id,
                    "business_date": request.business_date,
                    "play_type": selection.play_type,
                    "option_code": selection.option_code,
                },
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=422, detail="所选历史比赛或官方封盘赔率不存在")
            resolved.append(
                {
                    "match_id": row[0],
                    "official_match_code": row[1],
                    "odds_snapshot_id": row[2],
                    "odds_snapshot_time": row[3],
                    "play_type": row[4],
                    "option_code": row[5],
                    "option_name": row[6],
                    "sp_value": float(row[7]),
                    "handicap": float(row[8]) if row[8] is not None else None,
                    "is_single_allowed": bool(row[9]),
                    "is_pass_allowed": True,
                    "odds_source": "official_pre_close",
                }
            )
    return resolved


@router.post("/api/betting/time-machine/tickets")
def create_time_machine_ticket(request: CreateTimeMachineTicketRequest):
    """Persist a user-entered historical real ticket with canonical evidence."""
    _require_historical_date(request.business_date)
    with get_db() as conn:
        items = _resolve_selections(conn, request)
        calculation = _calculate(items, request.pass_type, request.multiple)
        ticket_id = create_real_ticket(
            conn,
            {
                "ticket_no": request.ticket_no,
                "purchase_time": request.business_date.isoformat(),
                "total_amount": calculation["total_cost"],
                "multiple": request.multiple,
                "pass_type": calculation["pass_type"],
                "theoretical_max_prize": calculation["max_prize"],
                "source_type": "time_machine_manual",
                "ocr_status": "not_applicable",
                "confirm_status": "confirmed",
                "settlement_status": "pending",
            },
        )
        if not ticket_id:
            raise HTTPException(status_code=500, detail="历史彩票创建失败")
        create_real_ticket_items_batch(conn, ticket_id, items)
    return {
        "status": "ok",
        "ticketUid": f"real:{ticket_id}",
        "legacyId": ticket_id,
        "source": "time_machine",
        "purchaseDate": request.business_date.isoformat(),
        "stake": calculation["total_cost"],
        "maxPrize": calculation["max_prize"],
        "betCount": calculation["bet_count"],
        "settlement": "已进入官方结果结算流程",
    }
