"""Daily competition snapshot job.

Runs at 23:50 daily (after generate_daily_review at 23:30, before
collect_health_metrics at 23:55).

1. Ensures current week round exists (creates on Monday)
2. Aggregates Agent pool stats from ticket_settlements (simulation)
3. Aggregates User pool stats from real_tickets + ticket_settlements
4. Writes competition_daily_snapshots
5. Finalizes round on Sunday
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.competition_storage import (
    compute_agent_daily_stats,
    compute_user_daily_stats,
    ensure_current_round,
    finalize_round,
    get_trend_data,
    upsert_daily_snapshot,
)


def _get_settled_agent_stake(conn, round_id: int) -> float:
    """Total agent stakes that have been settled within this round."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(ts.stake_amount), 0)
            FROM ticket_settlements ts
            JOIN competition_rounds cr ON cr.id = %(round_id)s
            WHERE ts.ticket_source = 'simulation'
              AND ts.created_at::date BETWEEN cr.round_start AND cr.round_end
            """,
            {"round_id": round_id},
        )
        return float(cur.fetchone()[0] or 0)


def _get_settled_user_stake(conn, round_id: int) -> float:
    """Total user stakes that have been settled within this round."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(ts.stake_amount), 0)
            FROM ticket_settlements ts
            JOIN competition_rounds cr ON cr.id = %(round_id)s
            WHERE ts.ticket_source = 'real'
              AND ts.created_at::date BETWEEN cr.round_start AND cr.round_end
            """,
            {"round_id": round_id},
        )
        return float(cur.fetchone()[0] or 0)


def run(dry_run: bool = False) -> dict[str, Any]:
    """Snapshot today's competition data for both pools."""
    today = date.today()
    snapshot_date = today

    if dry_run:
        return {
            "status": "dry_run",
            "snapshot_date": str(snapshot_date),
            "message": "competition snapshot (dry run)",
        }

    with get_db() as conn:
        # 1. Ensure current round exists
        round_data = ensure_current_round(conn)
        if not round_data or not round_data.get("id"):
            return {"status": "error", "message": "failed to get or create round"}

        round_id = round_data["id"]

        # 2. Compute today's stats for both pools
        agent = compute_agent_daily_stats(conn, snapshot_date)
        user = compute_user_daily_stats(conn, snapshot_date)

        # 3. Compute cumulative values from PREVIOUS snapshots
        #    (exclude today's snapshot if it already exists, to avoid double-counting)
        previous_snapshots = get_trend_data(conn, round_id)
        previous_snapshots = [s for s in previous_snapshots if s.get("snapshot_date") != str(snapshot_date)]

        # Previous cumulative values (from the last snapshot, if any)
        prev_agent_stake = 0.0
        prev_agent_prize = 0.0
        prev_user_stake = 0.0
        prev_user_prize = 0.0

        if previous_snapshots:
            last = previous_snapshots[-1]
            prev_agent_stake = last.get("agent_cumulative_stake", 0.0)
            prev_agent_prize = last.get("agent_cumulative_prize", 0.0)
            prev_user_stake = last.get("user_cumulative_stake", 0.0)
            prev_user_prize = last.get("user_cumulative_prize", 0.0)

        # Cumulative values: stakes are committed capital (for display),
        # but ROI uses ONLY settled amounts so the curve doesn't
        # show -100% just because matches haven't been played yet.
        agent_cum_stake = prev_agent_stake + agent["daily_stake"]
        agent_cum_prize = prev_agent_prize + agent["daily_prize"]

        # Settled-only cumulative for ROI computation
        settled_agent_stake = _get_settled_agent_stake(conn, round_id)
        settled_agent_pl = agent_cum_prize - settled_agent_stake
        agent_cum_roi = (settled_agent_pl / settled_agent_stake) if settled_agent_stake > 0 else 0.0

        user_cum_stake = prev_user_stake + user["daily_stake"]
        user_cum_prize = prev_user_prize + user["daily_prize"]

        settled_user_stake = _get_settled_user_stake(conn, round_id)
        settled_user_pl = user_cum_prize - settled_user_stake
        user_cum_roi = (settled_user_pl / settled_user_stake) if settled_user_stake > 0 else 0.0

        # 4. Write snapshot
        snap = upsert_daily_snapshot(
            conn,
            round_id=round_id,
            snapshot_date=snapshot_date,
            agent=agent,
            user=user,
            agent_cumulative_stake=agent_cum_stake,
            agent_cumulative_prize=agent_cum_prize,
            agent_cumulative_roi=agent_cum_roi,
            user_cumulative_stake=user_cum_stake,
            user_cumulative_prize=user_cum_prize,
            user_cumulative_roi=user_cum_roi,
        )

        # 5. Finalize round if today is Sunday
        finalized = None
        if today.weekday() == 6:  # Sunday
            finalized = finalize_round(conn, round_id)

    return {
        "status": "ok",
        "round_id": round_id,
        "round_label": round_data.get("round_label"),
        "snapshot_date": str(snapshot_date),
        "snapshot_id": snap.get("id"),
        "agent": agent,
        "user": user,
        "agent_cumulative_roi": round(agent_cum_roi, 6),
        "user_cumulative_roi": round(user_cum_roi, 6),
        "finalized": finalized,
    }
