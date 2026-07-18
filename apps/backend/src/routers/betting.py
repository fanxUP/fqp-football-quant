"""Unified betting center aggregation endpoints.

This layer keeps the old simulator, real-ticket, and competition APIs intact
while giving the frontend one ticket ledger contract to render.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from apps.backend.src.db import get_db
from scripts.business_time import business_now, business_today
from scripts.real_ticket_storage import (
    create_real_ticket,
    create_real_ticket_items_batch,
    list_real_tickets,
)
from scripts.simulator_calculator import (
    calculate_multi_all,
    parse_pass_types,
    validate_items,
)
from scripts.simulator_storage import list_simulator_tickets

router = APIRouter(tags=["betting"])

BETTING_LEDGER_SCAN_LIMIT = 300


class BettingTicketItemRequest(BaseModel):
    match_id: int
    play_type: str = "spf"
    option_code: str
    option_name: str
    sp_value: float
    handicap: float | None = None
    is_dan: bool = False
    is_single_allowed: bool = True
    is_pass_allowed: bool = True
    official_match_code: str | None = None


class CreateBettingTicketRequest(BaseModel):
    source: str = Field(..., description="simulator | real-user | real-agent")
    play_type: str = "spf"
    pass_type: str = "single"
    multiple: int = Field(1, ge=1, le=50)
    items: list[BettingTicketItemRequest]
    notes: str = ""
    ticket_no: str | None = None
    store_code: str | None = None
    ticket_image_url: str | None = None
    ocr_status: str | None = None


def _date_key(value: str | None) -> str:
    if not value:
        return "未归档"
    return value[:10]


def _settlement_status(status: str | None) -> str:
    if status in {"settled", "won", "lost", "cancelled"}:
        return str(status)
    return "pending"


def _ticket_number(value: str | None, purchase_date: str, legacy_id: int) -> str:
    """Return the persistent ledger number, with a migration-safe fallback."""
    if value:
        return value
    compact_date = purchase_date.replace("-", "") if purchase_date != "未归档" else "00000000"
    return f"{compact_date}{legacy_id:03d}"


def _map_simulator_ticket(ticket: dict) -> dict:
    stake = float(ticket.get("total_cost") or 0)
    purchase_date = _date_key(ticket.get("created_at"))
    legacy_id = int(ticket.get("id") or 0)
    return {
        "ticketUid": f"simulator:{ticket.get('id')}",
        "ticketNumber": _ticket_number(
            ticket.get("ledger_ticket_no"), purchase_date, legacy_id
        ),
        "legacyId": ticket.get("id"),
        "owner": "me",
        "kind": "simulation",
        "source": "manual",
        "status": _settlement_status(ticket.get("status")),
        "date": purchase_date,
        "createdAt": ticket.get("created_at"),
        "title": f"模拟票 #{ticket.get('id')}",
        "playType": ticket.get("play_type") or "spf",
        "passType": ticket.get("pass_type") or "single",
        "multiple": int(ticket.get("multiple") or 1),
        "betCount": int(ticket.get("bet_count") or 0),
        "matchCount": int(ticket.get("match_count") or 0),
        "stake": stake,
        "maxPrize": float(ticket.get("max_prize") or 0),
        "settledAmount": None,
        "profitLoss": None,
        "roi": None,
        "itemCount": int(ticket.get("item_count") or 0),
        "route": f"/simulator/history/{ticket.get('id')}",
    }


def _map_real_ticket(ticket: dict) -> dict:
    source_type = ticket.get("source_type") or ""
    owner = "agent" if source_type in {"agent", "agent_real"} else "me"
    stake = float(ticket.get("total_amount") or 0)
    purchase_date = _date_key(ticket.get("purchase_time") or ticket.get("created_at"))
    legacy_id = int(ticket.get("id") or 0)
    return {
        "ticketUid": f"real:{ticket.get('id')}",
        "ticketNumber": _ticket_number(
            ticket.get("ledger_ticket_no"), purchase_date, legacy_id
        ),
        "legacyId": ticket.get("id"),
        "owner": owner,
        "kind": "real",
        "source": "ocr" if ticket.get("ocr_status") == "recognized" else "manual",
        "status": _settlement_status(ticket.get("settlement_status")),
        "date": purchase_date,
        "createdAt": ticket.get("created_at"),
        "title": f"实票 #{ticket.get('id')}",
        "playType": "mixed",
        "passType": ticket.get("pass_type") or "single",
        "multiple": int(ticket.get("multiple") or 1),
        "betCount": None,
        "matchCount": int(ticket.get("item_count") or 0),
        "stake": stake,
        "maxPrize": ticket.get("theoretical_max_prize"),
        "settledAmount": None,
        "profitLoss": None,
        "roi": None,
        "itemCount": int(ticket.get("item_count") or 0),
        "route": f"/tickets/{ticket.get('id')}",
        "confirmStatus": ticket.get("confirm_status"),
        "linkedSimulationId": ticket.get("related_simulation_ticket_id"),
    }


def _map_agent_ticket(row: tuple) -> dict:
    ticket_id = row[0]
    stake = float(row[1] or 0)
    purchase_date = _date_key(row[6].isoformat() if row[6] else None)
    return {
        "ticketUid": f"agent:{ticket_id}",
        "ticketNumber": _ticket_number(
            row[12] if len(row) > 12 else None, purchase_date, int(ticket_id)
        ),
        "legacyId": ticket_id,
        "owner": "agent",
        "kind": "simulation",
        "source": "agent_recommendation",
        "status": _settlement_status(row[5]),
        "date": purchase_date,
        "createdAt": row[6].isoformat() if row[6] else None,
        "title": f"Agent 票 #{ticket_id}",
        "playType": "hhgg" if (row[7] or "single") != "single" else (row[8] or "spf"),
        "passType": row[7] or "single",
        "multiple": int(row[10] or 1) if len(row) > 10 else 1,
        "betCount": int(row[11] or 1) if len(row) > 11 else 1,
        "matchCount": int(row[9] or 0),
        "stake": stake,
        "maxPrize": None,
        "settledAmount": None,
        "profitLoss": None,
        "roi": None,
        "itemCount": int(row[9] or 0),
        "route": "/competition",
        "expectedValue": float(row[2] or 0),
        "strategyPool": row[3],
        "riskLevel": row[4],
    }


def _item_summary(row: tuple) -> dict:
    return {
        "matchId": row[0],
        "matchCode": row[1] or (str(row[0]) if row[0] is not None else "—"),
        "homeTeam": row[2] or "主队未识别",
        "awayTeam": row[3] or "客队未识别",
        "playType": row[4] or "spf",
        "optionCode": row[5] or "",
        "optionName": row[6] or row[5] or "",
        "spValue": _float(row[7]) if row[7] is not None else None,
        "oddsSource": row[8] if len(row) > 8 and row[8] else "official",
    }


def _attach_ticket_items(conn, tickets: list[dict], limit_per_ticket: int = 4) -> None:
    """Attach compact match summaries for ledger cards."""
    ids_by_source: dict[str, list[int]] = {"simulator": [], "real": [], "agent": []}
    for ticket in tickets:
        source, _, raw_id = str(ticket.get("ticketUid", "")).partition(":")
        if source in ids_by_source and raw_id.isdigit():
            ids_by_source[source].append(int(raw_id))

    item_map: dict[str, list[dict]] = {ticket["ticketUid"]: [] for ticket in tickets}

    def add_items(source: str, rows: list[tuple]) -> None:
        for row in rows:
            ticket_uid = f"{source}:{row[0]}"
            if ticket_uid not in item_map:
                continue
            if len(item_map[ticket_uid]) >= limit_per_ticket:
                continue
            item_map[ticket_uid].append(_item_summary(row[1:]))

    with conn.cursor() as cur:
        if ids_by_source["simulator"]:
            cur.execute(
                """
                SELECT sti.ticket_id, sti.match_id,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text),
                       m.home_team_name, m.away_team_name,
                       sti.play_type, sti.option_code, sti.option_name, sti.sp_value
                FROM simulator_ticket_items sti
                LEFT JOIN official_matches m ON m.id = sti.match_id
                WHERE sti.ticket_id = ANY(%(ids)s)
                ORDER BY sti.ticket_id, sti.id
                """,
                {"ids": ids_by_source["simulator"]},
            )
            add_items("simulator", list(cur.fetchall()))

        if ids_by_source["real"]:
            cur.execute(
                """
                SELECT rti.real_ticket_id, rti.match_id,
                       COALESCE(rti.official_match_code, m.raw_json->>'matchNumStr', m.official_match_code::text),
                       m.home_team_name, m.away_team_name,
                       rti.play_type, rti.option_code, rti.option_name, rti.sp_value
                FROM real_ticket_items rti
                LEFT JOIN official_matches m ON m.id = rti.match_id
                WHERE rti.real_ticket_id = ANY(%(ids)s)
                ORDER BY rti.real_ticket_id, rti.id
                """,
                {"ids": ids_by_source["real"]},
            )
            add_items("real", list(cur.fetchall()))

        if ids_by_source["agent"]:
            cur.execute(
                """
                SELECT sti.ticket_id, sti.match_id,
                       COALESCE(m.raw_json->>'matchNumStr', m.official_match_code::text),
                       m.home_team_name, m.away_team_name,
                       sti.play_type, sti.option_code, sti.option_name, sti.sp_value, sti.odds_source
                FROM simulation_ticket_items sti
                LEFT JOIN official_matches m ON m.id = sti.match_id
                WHERE sti.ticket_id = ANY(%(ids)s)
                ORDER BY sti.ticket_id, sti.id
                """,
                {"ids": ids_by_source["agent"]},
            )
            add_items("agent", list(cur.fetchall()))

    for ticket in tickets:
        ticket["items"] = item_map.get(ticket["ticketUid"], [])


def _float(value, default: float = 0.0) -> float:
    if value is None:
        return default
    return float(value)


def _iso(value) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _settlement_ticket_uid(ticket_source: str, ticket_id: int) -> str | None:
    if ticket_source == "simulator":
        return f"simulator:{ticket_id}"
    if ticket_source == "simulation":
        return f"agent:{ticket_id}"
    if ticket_source == "real":
        return f"real:{ticket_id}"
    return None


def _apply_settlements(tickets: list[dict], settlement_rows: list[tuple]) -> None:
    """Mutate unified tickets with realized settlement amounts."""
    by_uid = {ticket["ticketUid"]: ticket for ticket in tickets}
    for row in settlement_rows:
        ticket_uid = _settlement_ticket_uid(str(row[0]), int(row[1]))
        if not ticket_uid or ticket_uid not in by_uid:
            continue

        ticket = by_uid[ticket_uid]
        settled_at = _iso(row[2])
        net_prize = _float(row[7])
        profit_loss = _float(row[8])
        roi = _float(row[9])
        ticket["status"] = "settled"
        ticket["settledAmount"] = net_prize
        ticket["profitLoss"] = profit_loss
        ticket["roi"] = roi
        ticket["settledAt"] = settled_at
        ticket["isWon"] = bool(row[3])


def _fetch_recent_settlements(conn, limit: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ticket_source, ticket_id, settle_time, is_won,
                   stake_amount, prize_amount, tax_amount, net_prize,
                   profit_loss, roi
            FROM ticket_settlements
            WHERE ticket_source IN ('simulator', 'simulation', 'real')
            ORDER BY settle_time DESC
            LIMIT %(limit)s
            """,
            {"limit": max(limit * 4, 300)},
        )
        return list(cur.fetchall())


def _fetch_settled_betting_tickets(conn) -> list[dict]:
    """Return realized tickets that still have auditable betting items."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts.ticket_source, ts.ticket_id,
                   timezone('Asia/Shanghai', ts.settle_time AT TIME ZONE 'UTC') AS settle_time,
                   ts.is_won,
                   ts.stake_amount, ts.net_prize, ts.profit_loss, ts.roi,
                   rt.source_type, rt.ocr_status
            FROM ticket_settlements ts
            LEFT JOIN real_tickets rt
              ON ts.ticket_source = 'real' AND rt.id = ts.ticket_id
            WHERE ts.ticket_source IN ('simulator', 'simulation', 'real')
              AND (
                  (ts.ticket_source = 'simulator' AND EXISTS (
                      SELECT 1 FROM simulator_ticket_items sti
                      WHERE sti.ticket_id = ts.ticket_id
                  ))
                  OR (ts.ticket_source = 'simulation' AND EXISTS (
                      SELECT 1 FROM simulation_ticket_items sti
                      WHERE sti.ticket_id = ts.ticket_id
                  ))
                  OR (ts.ticket_source = 'real' AND EXISTS (
                      SELECT 1 FROM real_ticket_items rti
                      WHERE rti.real_ticket_id = ts.ticket_id
                  ))
              )
            ORDER BY ts.settle_time, ts.id
            """
        )
        rows = cur.fetchall()

    tickets: list[dict] = []
    for row in rows:
        ticket_source = str(row[0])
        ticket_id = int(row[1])
        is_real_agent = ticket_source == "real" and row[8] in {"agent", "agent_real"}
        owner = "agent" if ticket_source == "simulation" or is_real_agent else "me"
        source = "manual"
        if ticket_source == "simulation":
            source = "agent_recommendation"
        elif ticket_source == "real" and row[9] == "recognized":
            source = "ocr"
        settled_at = _iso(row[2])
        tickets.append(
            {
                "ticketUid": _settlement_ticket_uid(ticket_source, ticket_id),
                "owner": owner,
                "kind": "real" if ticket_source == "real" else "simulation",
                "source": source,
                "status": "settled",
                "date": _date_key(settled_at),
                "stake": _float(row[4]),
                "settledAmount": _float(row[5]),
                "profitLoss": _float(row[6]),
                "roi": _float(row[7]),
                "settledAt": settled_at,
                "isWon": bool(row[3]),
            }
        )
    return tickets


def _fetch_first_item_ticket_date(conn) -> date | None:
    """Return the first local purchase date that has at least one betting item."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MIN(ticket_date)
            FROM (
                SELECT (st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                           AS ticket_date
                FROM simulator_tickets st
                WHERE EXISTS (
                    SELECT 1 FROM simulator_ticket_items sti WHERE sti.ticket_id = st.id
                )
                UNION ALL
                SELECT (st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                FROM simulation_tickets st
                WHERE EXISTS (
                    SELECT 1 FROM simulation_ticket_items sti WHERE sti.ticket_id = st.id
                )
                UNION ALL
                SELECT (COALESCE(rt.purchase_time, rt.created_at)
                           AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                FROM real_tickets rt
                WHERE EXISTS (
                    SELECT 1 FROM real_ticket_items rti WHERE rti.real_ticket_id = rt.id
                )
            ) ticket_dates
            """
        )
        row = cur.fetchone()
    return row[0] if row and row[0] else None


def _merge_result_tickets(current: list[dict], settled: list[dict]) -> list[dict]:
    """Combine current pending tickets with the authoritative settled history."""
    return [ticket for ticket in current if ticket.get("status") == "pending"] + settled


def _empty_result_bucket() -> dict:
    return {
        "ticketCount": 0,
        "stake": 0.0,
        "settledAmount": 0.0,
        "profitLoss": 0.0,
        "roi": 0.0,
        "settled": 0,
        "pending": 0,
        "hitCount": 0,
    }


def _add_result_bucket(bucket: dict, ticket: dict) -> None:
    bucket["ticketCount"] += 1
    # 投入在出票时已经发生，不能等到结算后才进入彩票汇总。
    bucket["stake"] += _float(ticket.get("stake"))
    if ticket.get("status") != "settled":
        bucket["pending"] += 1
        return

    profit_loss = _float(ticket.get("profitLoss"))
    settled_amount = _float(ticket.get("settledAmount"))
    bucket["settledAmount"] += settled_amount
    bucket["profitLoss"] += profit_loss
    bucket["settled"] += 1
    if profit_loss > 0:
        bucket["hitCount"] += 1


def _round_result_bucket(bucket: dict) -> dict:
    stake = _float(bucket.get("stake"))
    profit_loss = _float(bucket.get("profitLoss"))
    return {
        **bucket,
        "stake": round(stake, 2),
        "settledAmount": round(bucket["settledAmount"], 2),
        "profitLoss": round(profit_loss, 2),
        "roi": round(profit_loss / stake, 4) if stake else 0.0,
    }


def _valid_ticket_date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _build_betting_results(
    tickets: list[dict],
    *,
    trend_start_date: date | None = None,
    today: date | None = None,
) -> dict:
    owners = {"me": _empty_result_bucket(), "agent": _empty_result_bucket()}
    by_source: dict[str, dict] = {}
    daily: dict[str, dict] = {}

    for ticket in tickets:
        owner = ticket.get("owner")
        if owner in owners:
            _add_result_bucket(owners[owner], ticket)

        source_key = f"{ticket.get('owner')}:{ticket.get('kind')}:{ticket.get('source')}"
        by_source.setdefault(source_key, _empty_result_bucket())
        _add_result_bucket(by_source[source_key], ticket)

        if ticket.get("status") != "settled":
            continue

        day = str(ticket.get("settledAt") or ticket.get("date") or "未归档")[:10]
        if day not in daily:
            daily[day] = {
                "date": day,
                "meStake": 0.0,
                "meProfitLoss": 0.0,
                "agentStake": 0.0,
                "agentProfitLoss": 0.0,
            }
        prefix = "agent" if owner == "agent" else "me"
        daily[day][f"{prefix}Stake"] += _float(ticket.get("stake"))
        if ticket.get("profitLoss") is not None:
            daily[day][f"{prefix}ProfitLoss"] += _float(ticket.get("profitLoss"))

    me = _round_result_bucket(owners["me"])
    agent = _round_result_bucket(owners["agent"])
    leader = "draw"
    if me["profitLoss"] > agent["profitLoss"]:
        leader = "me"
    elif agent["profitLoss"] > me["profitLoss"]:
        leader = "agent"

    if trend_start_date is None:
        item_ticket_dates = [
            parsed
            for ticket in tickets
            if int(ticket.get("itemCount") or 0) > 0
            if (parsed := _valid_ticket_date(ticket.get("date"))) is not None
        ]
        if item_ticket_dates:
            trend_start_date = min(item_ticket_dates)
        else:
            settled_dates = [
                parsed
                for ticket in tickets
                if ticket.get("status") == "settled"
                if (
                    parsed := _valid_ticket_date(
                        ticket.get("settledAt") or ticket.get("date")
                    )
                )
                is not None
            ]
            trend_start_date = min(settled_dates) if settled_dates else None

    if trend_start_date is not None:
        valid_daily_dates = [
            parsed
            for day in daily
            if (parsed := _valid_ticket_date(day)) is not None
        ]
        latest_data_date = max(valid_daily_dates, default=None)
        trend_end_date = max(
            today or business_today(),
            latest_data_date or trend_start_date,
            trend_start_date,
        )
        cursor = trend_start_date
        while cursor <= trend_end_date:
            day = cursor.isoformat()
            daily.setdefault(
                day,
                {
                    "date": day,
                    "meStake": 0.0,
                    "meProfitLoss": 0.0,
                    "agentStake": 0.0,
                    "agentProfitLoss": 0.0,
                },
            )
            cursor += timedelta(days=1)

        daily = {
            day: row
            for day, row in daily.items()
            if (parsed := _valid_ticket_date(day)) is not None
            and parsed >= trend_start_date
        }

    trend = []
    cumulative = {
        "meStake": 0.0,
        "meProfitLoss": 0.0,
        "agentStake": 0.0,
        "agentProfitLoss": 0.0,
    }
    for day in sorted(daily):
        row = daily[day]
        cumulative["meStake"] += row["meStake"]
        cumulative["meProfitLoss"] += row["meProfitLoss"]
        cumulative["agentStake"] += row["agentStake"]
        cumulative["agentProfitLoss"] += row["agentProfitLoss"]
        trend.append(
            {
                "date": day,
                "meDailyStake": round(row["meStake"], 2),
                "meDailyProfitLoss": round(row["meProfitLoss"], 2),
                "agentDailyStake": round(row["agentStake"], 2),
                "agentDailyProfitLoss": round(row["agentProfitLoss"], 2),
                "meCumulativeProfitLoss": round(cumulative["meProfitLoss"], 2),
                "agentCumulativeProfitLoss": round(cumulative["agentProfitLoss"], 2),
                "meCumulativeRoi": round(cumulative["meProfitLoss"] / cumulative["meStake"], 4)
                if cumulative["meStake"]
                else 0.0,
                "agentCumulativeRoi": round(
                    cumulative["agentProfitLoss"] / cumulative["agentStake"], 4
                )
                if cumulative["agentStake"]
                else 0.0,
            }
        )

    return {
        "owners": {"me": me, "agent": agent},
        "leader": leader,
        "bySource": {key: _round_result_bucket(value) for key, value in by_source.items()},
        "trend": trend,
        "updatedAt": _iso(business_now()),
    }


def _dump_items(items: list[BettingTicketItemRequest]) -> list[dict]:
    return [item.model_dump() for item in items]


def _calculate_multi_pass_ticket(items: list[dict], pass_type: str, multiple: int) -> dict:
    """Validate and calculate a canonical multi-pass ticket.

    Keep pass-type normalization in the calculator module so direct API callers
    get the same de-duplication semantics as the simulator endpoint and UI.
    """
    pass_types = parse_pass_types(pass_type)
    errors = [
        error
        for selected_pass_type in pass_types
        for error in validate_items(items, selected_pass_type)
    ]
    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors})

    try:
        result = calculate_multi_all(items, pass_types, multiple)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
    return result


def _create_real_betting_ticket(conn, req: CreateBettingTicketRequest) -> dict:
    items = _dump_items(req.items)
    calc = _calculate_multi_pass_ticket(items, req.pass_type, req.multiple)

    source_type = "agent" if req.source == "real-agent" else "user_manual"
    ocr_status = req.ocr_status or ("recognized" if req.ticket_image_url else "not_applicable")
    ticket_id = create_real_ticket(
        conn,
        {
            "ticket_image_url": req.ticket_image_url,
            "ticket_no": req.ticket_no,
            "store_code": req.store_code,
            "total_amount": calc["total_cost"],
            "multiple": req.multiple,
            "pass_type": calc["pass_type"],
            "theoretical_max_prize": calc["max_prize"],
            "source_type": source_type,
            "ocr_status": ocr_status,
            "confirm_status": "confirmed",
            "settlement_status": "pending",
        },
    )
    if not ticket_id:
        raise HTTPException(status_code=500, detail="创建彩票失败")

    create_real_ticket_items_batch(conn, ticket_id, items)
    return {
        "status": "ok",
        "ticketUid": f"real:{ticket_id}",
        "legacyId": ticket_id,
        "owner": "agent" if req.source == "real-agent" else "me",
        "kind": "real",
        "source": "ocr" if ocr_status == "recognized" else "manual",
        "stake": calc["total_cost"],
        "maxPrize": calc["max_prize"],
        "betCount": calc["bet_count"],
        "route": f"/tickets/{ticket_id}",
    }


@router.post("/api/betting/tickets")
def create_betting_ticket(req: CreateBettingTicketRequest):
    """Create a betting-center ticket.

    Simulator tickets still use the legacy simulator endpoint for bankroll
    deduction. Real-user and real-agent tickets are persisted as real tickets
    and immediately appear in the unified lottery ledger.
    """
    if req.source not in {"simulator", "real-user", "real-agent"}:
        raise HTTPException(
            status_code=400, detail="source must be simulator, real-user, or real-agent"
        )
    if not req.items:
        raise HTTPException(status_code=400, detail="至少需要选择一场比赛")
    if req.source == "simulator":
        raise HTTPException(
            status_code=409, detail="模拟票请继续使用 /api/simulator/tickets 以完成虚拟余额扣款"
        )

    with get_db() as conn:
        return _create_real_betting_ticket(conn, req)


def _collect_betting_tickets(conn, limit: int) -> list[dict]:
    simulator = [_map_simulator_ticket(t) for t in list_simulator_tickets(conn, limit=limit)]
    real = [_map_real_ticket(t) for t in list_real_tickets(conn, limit=limit)]

    agent: list[dict] = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT st.id, st.suggested_stake, st.expected_value,
                   st.strategy_pool, st.risk_level, st.ticket_status,
                   st.created_at, st.pass_type, st.ticket_type,
                   COUNT(sti.id) AS item_count, st.multiple, st.bet_count,
                   st.ledger_ticket_no
            FROM simulation_tickets st
            JOIN simulation_ticket_items sti ON sti.ticket_id = st.id
            WHERE st.ticket_status <> 'cancelled'
            GROUP BY st.id
            ORDER BY st.created_at DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        agent = [_map_agent_ticket(row) for row in cur.fetchall()]

    tickets = [*simulator, *real, *agent]
    _apply_settlements(tickets, _fetch_recent_settlements(conn, limit))
    _attach_ticket_items(conn, tickets)
    return tickets


@router.get("/api/betting/tickets")
def list_betting_tickets(
    owner: str | None = Query(None, description="me | agent"),
    date: str | None = Query(None, description="YYYY-MM-DD"),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
):
    """Return a unified ticket ledger for the betting center."""
    with get_db() as conn:
        # ``limit`` controls the response page, not the aggregate totals. Scan
        # the complete supported ledger window before filtering and slicing.
        tickets = _collect_betting_tickets(conn, BETTING_LEDGER_SCAN_LIMIT)

    if owner:
        tickets = [ticket for ticket in tickets if ticket["owner"] == owner]
    if date:
        tickets = [ticket for ticket in tickets if ticket["date"] == date]
    if status:
        tickets = [ticket for ticket in tickets if ticket["status"] == status]

    tickets.sort(key=lambda ticket: ticket.get("createdAt") or "", reverse=True)

    summary = {
        "total": len(tickets),
        "stake": round(sum(float(ticket.get("stake") or 0) for ticket in tickets), 2),
        "settled": len([ticket for ticket in tickets if ticket.get("status") == "settled"]),
        "pending": len([ticket for ticket in tickets if ticket.get("status") == "pending"]),
        "profitLoss": round(sum(float(ticket.get("profitLoss") or 0) for ticket in tickets), 2),
    }
    return {"tickets": tickets[:limit], "total": len(tickets), "summary": summary}


@router.get("/api/betting/results")
def get_betting_results(limit: int = Query(300, ge=1, le=500)):
    """Return P&L, ROI, hit counts, and trend across unified betting sources."""
    with get_db() as conn:
        current = _collect_betting_tickets(conn, limit)
        settled = _fetch_settled_betting_tickets(conn)
        trend_start_date = _fetch_first_item_ticket_date(conn)
    return _build_betting_results(
        _merge_result_tickets(current, settled),
        trend_start_date=trend_start_date,
    )
