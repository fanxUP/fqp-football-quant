"""Simulator endpoints — 体彩官方投注模拟器 (virtual betting with bankroll)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from apps.backend.src.db import get_db
from scripts.real_ticket_storage import create_bankroll_transaction
from scripts.simulator_calculator import (
    calculate_multi_all,
    get_available_pass_types,
    parse_pass_types,
    validate_items,
)
from scripts.simulator_storage import (
    create_simulator_items_batch,
    create_simulator_ticket,
    delete_simulator_ticket,
    ensure_simulator_bankroll,
    get_bankroll_summary,
    get_simulator_ticket,
    list_bankroll_transactions,
    list_simulator_tickets,
    reset_bankroll,
)
from scripts.sporttery_sales import get_sporttery_sales_window

router = APIRouter(tags=["simulator"])

POOL_PLAY_TYPES = {
    "HAD": "spf",
    "HHAD": "rqspf",
    "TTG": "zjq",
    "CRS": "bf",
    "HAFU": "bqc",
}


def _pool_capabilities(raw_json: dict | None) -> dict[str, dict[str, bool]]:
    capabilities: dict[str, dict[str, bool]] = {}
    for pool in (raw_json or {}).get("poolList", []):
        play_type = POOL_PLAY_TYPES.get(pool.get("poolCode", ""))
        if not play_type:
            continue
        capabilities[play_type] = {
            "single": any(
                pool.get(field, 0) == 1
                for field in ("single", "bettingSingle", "cbtSingle", "intSingle")
            ),
            "pass": any(
                pool.get(field, 0) == 1
                for field in ("allUp", "bettingAllup", "cbtAllUp", "intAllUp")
            ),
        }
    return capabilities


# ---- Request models ----


class BetItemRequest(BaseModel):
    match_id: int
    play_type: str = "spf"
    option_code: str
    option_name: str
    sp_value: float
    handicap: float | None = None
    is_dan: bool = False
    is_single_allowed: bool = True
    is_pass_allowed: bool = True


class CalculateRequest(BaseModel):
    items: list[BetItemRequest]
    pass_type: str = "single"
    multiple: int = 1


class SubmitTicketRequest(BaseModel):
    play_type: str = "spf"
    pass_type: str = "single"
    multiple: int = 1
    items: list[BetItemRequest]
    notes: str = ""


class ResetBankrollRequest(BaseModel):
    confirm: bool = False


# ---- Match browsing ----


@router.get("/api/simulator/matches")
def list_matches(
    date: str | None = Query(None, description="Business date (YYYY-MM-DD), optional"),
    league_name: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List sellable matches with odds for all 5 play types."""
    sales_window = get_sporttery_sales_window()
    if not sales_window.is_open:
        return {"matches": [], "total": 0, "sales_window": sales_window.as_dict()}

    with get_db() as conn:
        with conn.cursor() as cur:
            # A stale selling flag must never expose a settled or already-started match.
            where_parts = [
                "m.sale_status = 'selling'",
                "LOWER(COALESCE(m.match_status, '')) IN ('scheduled', 'selling', 'not_started')",
                "m.kickoff_time > timezone('Asia/Shanghai', NOW())",
                "(m.sale_stop_time IS NULL OR m.sale_stop_time > timezone('Asia/Shanghai', NOW()))",
            ]
            params: dict = {"limit": limit}

            if date:
                where_parts.append("m.business_date = %(date)s")
                params["date"] = date

            if league_name:
                where_parts.append("m.league_name = %(league_name)s")
                params["league_name"] = league_name

            where_clause = " AND ".join(where_parts)

            sql_matches = f"""
                SELECT m.id, m.business_date, m.league_name,
                       m.home_team_name, m.away_team_name,
                       m.kickoff_time, m.match_status,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text) AS match_num_str,
                       m.raw_json
                FROM official_matches m
                WHERE {where_clause}
                ORDER BY m.kickoff_time ASC
                LIMIT %(limit)s
            """
            cur.execute(sql_matches, params)
            match_rows = cur.fetchall()

            if not match_rows:
                return {"matches": [], "total": 0, "sales_window": sales_window.as_dict()}

            match_ids = [r[0] for r in match_rows]

            # Bulk-fetch latest odds for all match_ids.
            # Use DISTINCT ON to get the latest snapshot per (match_id, play_type, option_code)
            sql_odds = """
                SELECT DISTINCT ON (match_id, play_type, option_code)
                    match_id, play_type, option_code, option_name,
                    sp_value, handicap, is_single_allowed
                FROM official_odds_snapshots
                WHERE match_id = ANY(%(match_ids)s)
                  AND is_open = true
                ORDER BY match_id, play_type, option_code, snapshot_time DESC
            """
            cur.execute(sql_odds, {"match_ids": match_ids})
            odds_rows = cur.fetchall()

    # Build response — group odds by match and play_type
    matches_map: dict[int, dict] = {}
    for mr in match_rows:
        capabilities = _pool_capabilities(
            mr[8] if len(mr) > 8 and isinstance(mr[8], dict) else None
        )
        matches_map[mr[0]] = {
            "match_id": mr[0],
            "business_date": str(mr[1]),
            "league_name": mr[2],
            "home_team_name": mr[3],
            "away_team_name": mr[4],
            "kickoff_time": mr[5].isoformat() if hasattr(mr[5], "isoformat") else str(mr[5]),
            "match_status": mr[6],
            "match_num_str": mr[7] if len(mr) > 7 else "",
            "_pool_capabilities": capabilities,
            "odds": {},
        }

    # Pre-fill empty odds groups for all 5 play types
    for mid in matches_map:
        capabilities = matches_map[mid]["_pool_capabilities"]
        matches_map[mid]["odds"] = {
            "spf": {
                "is_single_allowed": capabilities.get("spf", {}).get("single", False),
                "is_pass_allowed": capabilities.get("spf", {}).get("pass", False),
                "options": [],
            },
            "rqspf": {
                "handicap": None,
                "is_single_allowed": capabilities.get("rqspf", {}).get("single", False),
                "is_pass_allowed": capabilities.get("rqspf", {}).get("pass", False),
                "options": [],
            },
            "zjq": {
                "is_single_allowed": capabilities.get("zjq", {}).get("single", False),
                "is_pass_allowed": capabilities.get("zjq", {}).get("pass", False),
                "options": [],
            },
            "bf": {
                "is_single_allowed": capabilities.get("bf", {}).get("single", False),
                "is_pass_allowed": capabilities.get("bf", {}).get("pass", False),
                "options": [],
            },
            "bqc": {
                "is_single_allowed": capabilities.get("bqc", {}).get("single", False),
                "is_pass_allowed": capabilities.get("bqc", {}).get("pass", False),
                "options": [],
            },
        }

    for orow in odds_rows:
        mid = orow[0]
        play_type = orow[1]
        option_code = orow[2]
        option_name = orow[3]
        sp_value = float(orow[4]) if orow[4] else 0.0
        handicap = float(orow[5]) if orow[5] else None
        is_single = orow[6] if len(orow) > 6 else False

        if mid not in matches_map:
            continue

        odds = matches_map[mid]["odds"]
        if play_type == "spf":
            odds["spf"]["is_single_allowed"] = odds["spf"]["is_single_allowed"] or is_single
            odds["spf"]["options"].append(
                {
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_value,
                }
            )
        elif play_type == "rqspf":
            if handicap is not None:
                odds["rqspf"]["handicap"] = handicap
            odds["rqspf"]["is_single_allowed"] = odds["rqspf"]["is_single_allowed"] or is_single
            odds["rqspf"]["options"].append(
                {
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_value,
                }
            )
        elif play_type in ("total_goals", "zjq"):
            odds["zjq"]["is_single_allowed"] = odds["zjq"]["is_single_allowed"] or is_single
            odds["zjq"]["options"].append(
                {
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_value,
                }
            )
        elif play_type in ("score", "bf"):
            odds["bf"]["is_single_allowed"] = odds["bf"]["is_single_allowed"] or is_single
            odds["bf"]["options"].append(
                {
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_value,
                }
            )
        elif play_type in ("half_full", "bqc"):
            odds["bqc"]["is_single_allowed"] = odds["bqc"]["is_single_allowed"] or is_single
            odds["bqc"]["options"].append(
                {
                    "option_code": option_code,
                    "option_name": option_name,
                    "sp_value": sp_value,
                }
            )

    # Sort options for each play type (SPF: 3→1→0, ZJQ: 0→7+, BF: by code, BQC: 33→00)
    for m in matches_map.values():
        m.pop("_pool_capabilities", None)
        for pt in m["odds"]:
            opts = m["odds"][pt].get("options", [])
            if pt == "spf" or pt == "rqspf":
                order = {"3": 0, "h": 0, "1": 1, "d": 1, "0": 2, "a": 2}
                opts.sort(key=lambda o: order.get(o["option_code"], 99))
            elif pt == "zjq":
                order = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7+": 7}
                opts.sort(key=lambda o: order.get(o["option_code"], 99))
            elif pt == "bqc":
                order = {
                    "33": 0,
                    "31": 1,
                    "30": 2,
                    "13": 3,
                    "11": 4,
                    "10": 5,
                    "03": 6,
                    "01": 7,
                    "00": 8,
                }
                opts.sort(key=lambda o: order.get(o["option_code"], 99))

    result = sorted(matches_map.values(), key=lambda m: m["kickoff_time"])
    return {
        "matches": result,
        "total": len(result),
        "sales_window": sales_window.as_dict(),
    }


# ---- Calculation ----


@router.post("/api/simulator/calculate")
def calculate(req: CalculateRequest):
    """Calculate bet count, total cost, and max prize without submitting."""
    items = [item.model_dump() for item in req.items]

    # Validate
    pass_types = parse_pass_types(req.pass_type)
    errors = [error for pass_type in pass_types for error in validate_items(items, pass_type)]
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    # Validate multiple
    if req.multiple < 1 or req.multiple > 50:
        raise HTTPException(status_code=400, detail="倍数必须在 1-50 之间")

    try:
        result = calculate_multi_all(items, pass_types, req.multiple)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Add available pass types for the frontend dropdown
    result["available_pass_types"] = get_available_pass_types(items)

    return result


# ---- Ticket CRUD ----


@router.post("/api/simulator/tickets")
def submit_ticket(req: SubmitTicketRequest):
    """Submit a simulated bet: validate, deduct bankroll, store ticket."""
    sales_window = get_sporttery_sales_window()
    if not sales_window.is_open:
        raise HTTPException(status_code=409, detail=sales_window.message)

    items = [item.model_dump() for item in req.items]

    # Validate
    pass_types = parse_pass_types(req.pass_type)
    errors = [error for pass_type in pass_types for error in validate_items(items, pass_type)]
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    if req.multiple < 1 or req.multiple > 50:
        raise HTTPException(status_code=400, detail="倍数必须在 1-50 之间")

    # Calculate
    try:
        calc = calculate_multi_all(items, pass_types, req.multiple)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    total_cost = calc["total_cost"]

    with get_db() as conn:
        # Check bankroll
        account = ensure_simulator_bankroll(conn)
        if float(account["current_balance"]) < total_cost:
            raise HTTPException(
                status_code=400,
                detail=f"虚拟余额不足！当前余额 ¥{account['current_balance']:,.2f}，需要 ¥{total_cost:,.2f}",
            )

        # Determine overall play_type
        play_types: set[str] = {it.get("play_type", "spf") for it in items}
        overall_play_type = req.play_type if len(play_types) == 1 else "hhgg"

        # Create ticket
        ticket_id = create_simulator_ticket(
            conn,
            {
                "play_type": overall_play_type,
                "pass_type": req.pass_type,
                "multiple": req.multiple,
                "total_cost": total_cost,
                "bet_count": calc["bet_count"],
                "max_prize": calc["max_prize"],
                "match_count": len({item.get("match_id") for item in items}),
                "status": "pending",
                "notes": req.notes,
            },
        )

        if not ticket_id:
            raise HTTPException(status_code=500, detail="创建票单失败")

        # Create items
        create_simulator_items_batch(conn, ticket_id, items)

        # Deduct bankroll (negative amount = deduction)
        create_bankroll_transaction(
            conn,
            {
                "account_type": "simulator",
                "transaction_type": "stake",
                "amount": -total_cost,
                "related_ticket_id": ticket_id,
                "remark": f"模拟投注 #{ticket_id} ({req.pass_type} {req.multiple}倍)",
            },
        )

        # Fetch created ticket
        ticket = get_simulator_ticket(conn, ticket_id)

    return {"status": "ok", "ticket": ticket}


@router.get("/api/simulator/tickets")
def list_tickets(
    status: str | None = Query(None, description="Filter by status: pending/settled/cancelled"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List simulator tickets."""
    with get_db() as conn:
        tickets = list_simulator_tickets(conn, status=status, limit=limit, offset=offset)
    return {"tickets": tickets, "total": len(tickets)}


@router.get("/api/simulator/tickets/{ticket_id}")
def get_ticket(ticket_id: int):
    """Get a single simulator ticket with items and settlement info."""
    with get_db() as conn:
        ticket = get_simulator_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="票单不存在")

        # Check for settlement
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, ticket_source, ticket_id, settle_time, is_won,
                          stake_amount, prize_amount, tax_amount, net_prize,
                          profit_loss, roi, settlement_detail_json, created_at
                   FROM ticket_settlements
                   WHERE ticket_source = 'simulator' AND ticket_id = %(ticket_id)s""",
                {"ticket_id": ticket_id},
            )
            srow = cur.fetchone()
            if srow:
                ticket["settlement"] = {
                    "id": srow[0],
                    "ticket_source": srow[1],
                    "ticket_id": srow[2],
                    "settle_time": srow[3].isoformat()
                    if hasattr(srow[3], "isoformat")
                    else str(srow[3]),
                    "is_won": srow[4],
                    "stake_amount": float(srow[5]) if srow[5] else 0,
                    "prize_amount": float(srow[6]) if srow[6] else 0,
                    "tax_amount": float(srow[7]) if srow[7] else 0,
                    "net_prize": float(srow[8]) if srow[8] else 0,
                    "profit_loss": float(srow[9]) if srow[9] else 0,
                    "roi": float(srow[10]) if srow[10] else 0,
                    "settlement_detail_json": srow[11],
                }

    return {"ticket": ticket}


@router.delete("/api/simulator/tickets/{ticket_id}")
def cancel_ticket(ticket_id: int):
    """Cancel a pending simulator ticket and refund bankroll."""
    with get_db() as conn:
        ticket = get_simulator_ticket(conn, ticket_id)
        if not ticket:
            raise HTTPException(status_code=404, detail="票单不存在")
        if ticket["status"] != "pending":
            raise HTTPException(status_code=400, detail="只能取消待结算的票单")

        total_cost = float(ticket["total_cost"])

        # Refund
        create_bankroll_transaction(
            conn,
            {
                "account_type": "simulator",
                "transaction_type": "refund",
                "amount": total_cost,
                "related_ticket_id": ticket_id,
                "remark": f"取消模拟投注 #{ticket_id}（退款）",
            },
        )

        # Delete ticket
        delete_simulator_ticket(conn, ticket_id)

    return {"status": "ok", "refunded": total_cost}


# ---- Bankroll ----


@router.get("/api/simulator/bankroll")
def bankroll_summary():
    """Get simulator bankroll summary."""
    with get_db() as conn:
        return get_bankroll_summary(conn)


@router.get("/api/simulator/bankroll/transactions")
def bankroll_transactions(
    limit: int = Query(50, ge=1, le=200),
):
    """List bankroll transactions."""
    with get_db() as conn:
        txn = list_bankroll_transactions(conn, limit=limit)
    return {"transactions": txn, "total": len(txn)}


@router.post("/api/simulator/bankroll/reset")
def reset_bankroll_endpoint(req: ResetBankrollRequest):
    """Reset simulator bankroll to initial balance."""
    if not req.confirm:
        raise HTTPException(status_code=400, detail="请确认重置操作（confirm: true）")
    with get_db() as conn:
        result = reset_bankroll(conn)
    return result
