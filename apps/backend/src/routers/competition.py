"""Competition API — two-pool ROI competition (Agent vs User).

Agent pool: simulation_tickets, ¥500/day virtual budget, daily reset.
User pool: real_tickets and user-created simulator_tickets.
Competition judged by cumulative ROI over weekly rounds (Mon-Sun).
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, Query

from apps.backend.src.db import get_db
from scripts.business_time import business_today
from scripts.competition_storage import (
    ensure_current_round,
    get_round,
    get_summary,
    get_trend_data,
    list_rounds,
)
from scripts.daily_decision_storage import list_agent_daily_decisions

router = APIRouter(tags=["competition"])


@router.get("/api/competition/decisions")
def get_agent_daily_decisions(limit: int = Query(14, ge=1, le=90)):
    """Return recent Agent buy-or-abstain decisions for review."""
    with get_db() as conn:
        decisions = list_agent_daily_decisions(conn, limit=limit)
    return {"decisions": decisions, "total": len(decisions)}


@router.get("/api/competition/rounds/current")
def get_current_round():
    """Get the current active competition round with daily snapshots.

    Returns the current week's round (Mon-Sun). Creates it if it
    doesn't exist yet (e.g., on Monday).
    """
    with get_db() as conn:
        round_data = ensure_current_round(conn)
        if not round_data or not round_data.get("id"):
            raise HTTPException(500, "Failed to get or create current round")

        # Load full round with snapshots
        full = get_round(conn, round_data["id"])
        if not full:
            raise HTTPException(500, "Failed to load round")

        # Add trend data
        full["trend"] = get_trend_data(conn, round_data["id"])

        # Days remaining
        today = business_today()
        round_end = date.fromisoformat(full["round_end"]) if full.get("round_end") else today
        days_left = (round_end - today).days
        full["days_remaining"] = max(0, days_left)
        full["total_days"] = 7

    return full


@router.get("/api/competition/rounds")
def get_rounds(
    limit: int = Query(20, ge=1, le=100),
    status: str | None = Query(None, description="Filter: active | completed"),
):
    """List past competition rounds, newest first."""
    if status and status not in ("active", "completed"):
        raise HTTPException(400, "status must be 'active' or 'completed'")

    with get_db() as conn:
        rounds = list_rounds(conn, limit=limit, status=status)

    return {"rounds": rounds, "total": len(rounds)}


@router.get("/api/competition/rounds/{round_id}")
def get_round_detail(round_id: int):
    """Get a single round with all daily snapshots and trend data."""
    with get_db() as conn:
        r = get_round(conn, round_id)
        if not r:
            raise HTTPException(404, f"Round {round_id} not found")
        r["trend"] = get_trend_data(conn, round_id)

    return r


@router.get("/api/competition/trend")
def get_trend(
    round_id: int | None = Query(None, description="Round ID. Defaults to current."),
):
    """Get cumulative ROI trend data for chart rendering.

    Returns list of daily cumulative ROI for both agent and user pools.
    """
    with get_db() as conn:
        if round_id is None:
            current = ensure_current_round(conn)
            if not current or not current.get("id"):
                return {"trend": [], "note": "no active round"}
            round_id = current["id"]

        trend = get_trend_data(conn, round_id)

    return {"round_id": round_id, "trend": trend}


@router.get("/api/competition/summary")
def get_competition_summary():
    """Get overall competition stats across all rounds."""
    with get_db() as conn:
        summary = get_summary(conn)

        # Current round
        current = ensure_current_round(conn)

    summary["current_round"] = {
        "id": current.get("id"),
        "round_label": current.get("round_label"),
        "status": current.get("status"),
    }
    return summary


@router.get("/api/competition/rounds/current/tickets")
def get_current_round_tickets():
    """Get agent simulation tickets for the current competition round."""
    with get_db() as conn:
        current = ensure_current_round(conn)
        if not current or not current.get("id"):
            raise HTTPException(500, "Failed to get current round")

        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                st.id, st.suggested_stake, st.expected_value,
                st.strategy_pool, st.risk_level, st.ticket_status,
                st.created_at, st.pass_type, st.ticket_type,
                sti.id AS item_id,
                sti.play_type, sti.option_code, sti.option_name,
                sti.sp_value, sti.model_probability,
                m.home_team_name, m.away_team_name, m.league_name,
                m.kickoff_time, m.official_match_code
            FROM simulation_tickets st
            JOIN simulation_ticket_items sti ON sti.ticket_id = st.id
            JOIN official_matches m ON m.id = sti.match_id
            WHERE (st.created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
                  BETWEEN %(start)s AND %(end)s
              AND st.ticket_status IN ('generated', 'activated', 'settled')
            ORDER BY st.id, sti.id
            """,
            {
                "start": current["round_start"],
                "end": current["round_end"],
            },
        )
        rows = cur.fetchall()

    # Group items by ticket_id (for 2x1 / 3x1 parlays)
    tickets_by_id: dict[int, dict] = {}
    for r in rows:
        tid = r[0]
        if tid not in tickets_by_id:
            tickets_by_id[tid] = {
                "id": tid,
                "stake": float(r[1] or 0),
                "ev": float(r[2] or 0),
                "strategy_pool": r[3],
                "risk_level": r[4],
                "status": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
                "pass_type": r[7] or "single",
                "ticket_type": r[8] or "single",
                "items": [],
            }
        tickets_by_id[tid]["items"].append(
            {
                "item_id": r[9],
                "play_type": r[10],
                "option_code": r[11],
                "option_name": r[12],
                "sp_value": float(r[13] or 0),
                "model_probability": float(r[14] or 0),
                "home_team": r[15],
                "away_team": r[16],
                "league": r[17],
                "kickoff_time": r[18].isoformat() if r[18] else None,
                "match_code": r[19],
            }
        )

    tickets = list(tickets_by_id.values())

    return {
        "round_id": current["id"],
        "round_label": current["round_label"],
        "tickets": tickets,
        "total": len(tickets),
        "total_stake": round(sum(t["stake"] for t in tickets), 2),
    }
