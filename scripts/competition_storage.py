"""Competition storage layer — two-pool ROI competition (Agent vs User).

Follows the same psycopg2 CRUD pattern as simulator_storage.py and
real_ticket_storage.py. All functions accept conn and call conn.commit()
internally.

Agent pool: simulation_tickets → ticket_settlements (ticket_source='simulation')
User pool:  real_tickets       → ticket_settlements (ticket_source='real')
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

AGENT_DAILY_BUDGET = 500.00  # Agent daily budget in CNY


def _iso(val: Any) -> str | None:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _date_str(val: Any) -> str | None:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ── Round helpers ───────────────────────────────────────────────────

def _monday_of_week(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _sunday_of_week(d: date) -> date:
    """Return the Sunday of the week containing d."""
    return d + timedelta(days=(6 - d.weekday()))


def _round_label(monday: date) -> str:
    """Generate round label like '2026-W27'."""
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _round_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "round_label": r[1],
        "round_start": _date_str(r[2]),
        "round_end": _date_str(r[3]),
        "agent_total_stake": float(r[4] or 0),
        "agent_total_prize": float(r[5] or 0),
        "agent_profit_loss": float(r[6] or 0),
        "agent_roi": float(r[7] or 0),
        "user_total_stake": float(r[8] or 0),
        "user_total_prize": float(r[9] or 0),
        "user_profit_loss": float(r[10] or 0),
        "user_roi": float(r[11] or 0),
        "winner": r[12],
        "status": r[13],
        "created_at": _iso(r[14]),
        "updated_at": _iso(r[15]),
    }


def _snapshot_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "round_id": r[1],
        "snapshot_date": _date_str(r[2]),
        "agent_daily_stake": float(r[3] or 0),
        "agent_daily_prize": float(r[4] or 0),
        "agent_daily_profit_loss": float(r[5] or 0),
        "agent_daily_roi": float(r[6] or 0),
        "agent_cumulative_stake": float(r[7] or 0),
        "agent_cumulative_prize": float(r[8] or 0),
        "agent_cumulative_roi": float(r[9] or 0),
        "agent_budget_usage_rate": float(r[10] or 0),
        "agent_ticket_count": r[11],
        "user_daily_stake": float(r[12] or 0),
        "user_daily_prize": float(r[13] or 0),
        "user_daily_profit_loss": float(r[14] or 0),
        "user_daily_roi": float(r[15] or 0),
        "user_cumulative_stake": float(r[16] or 0),
        "user_cumulative_prize": float(r[17] or 0),
        "user_cumulative_roi": float(r[18] or 0),
        "user_ticket_count": r[19],
        "created_at": _iso(r[20]),
    }


# ── Round management ────────────────────────────────────────────────

def ensure_current_round(conn: Any) -> dict:
    """Get or create the competition round for the current week (Mon-Sun).

    Returns the round dict. Creates a new round if today is Monday and
    no active round exists, or if the current round's week has passed.
    """
    today = date.today()
    monday = _monday_of_week(today)
    sunday = _sunday_of_week(today)

    sql_select = """
        SELECT id, round_label, round_start, round_end,
               agent_total_stake, agent_total_prize, agent_profit_loss, agent_roi,
               user_total_stake, user_total_prize, user_profit_loss, user_roi,
               winner, status, created_at, updated_at
        FROM competition_rounds
        WHERE round_start = %(monday)s AND round_end = %(sunday)s
        LIMIT 1
    """
    sql_insert = """
        INSERT INTO competition_rounds
            (round_label, round_start, round_end, status, created_at, updated_at)
        VALUES (%(label)s, %(monday)s, %(sunday)s, 'active', now(), now())
        RETURNING id
    """

    with conn.cursor() as cur:
        cur.execute(sql_select, {"monday": monday, "sunday": sunday})
        row = cur.fetchone()
        if row:
            conn.commit()
            return _round_row(row)

        cur.execute(sql_insert, {
            "label": _round_label(monday),
            "monday": monday,
            "sunday": sunday,
        })
        cur.execute(sql_select, {"monday": monday, "sunday": sunday})
        row = cur.fetchone()
    conn.commit()
    return _round_row(row) if row else {}


def get_round(conn: Any, round_id: int) -> dict | None:
    """Get a single round with all its daily snapshots."""
    sql_round = """
        SELECT id, round_label, round_start, round_end,
               agent_total_stake, agent_total_prize, agent_profit_loss, agent_roi,
               user_total_stake, user_total_prize, user_profit_loss, user_roi,
               winner, status, created_at, updated_at
        FROM competition_rounds WHERE id = %(id)s
    """
    sql_snapshots = """
        SELECT id, round_id, snapshot_date,
               agent_daily_stake, agent_daily_prize, agent_daily_profit_loss,
               agent_daily_roi, agent_cumulative_stake, agent_cumulative_prize,
               agent_cumulative_roi, agent_budget_usage_rate, agent_ticket_count,
               user_daily_stake, user_daily_prize, user_daily_profit_loss,
               user_daily_roi, user_cumulative_stake, user_cumulative_prize,
               user_cumulative_roi, user_ticket_count, created_at
        FROM competition_daily_snapshots
        WHERE round_id = %(round_id)s
        ORDER BY snapshot_date
    """
    with conn.cursor() as cur:
        cur.execute(sql_round, {"id": round_id})
        r = cur.fetchone()
        if not r:
            return None
        cur.execute(sql_snapshots, {"round_id": round_id})
        snaps = [_snapshot_row(s) for s in cur.fetchall()]
    result = _round_row(r)
    result["snapshots"] = snaps
    return result


def list_rounds(conn: Any, limit: int = 20, status: str | None = None) -> list[dict]:
    """List competition rounds, newest first."""
    where = "WHERE cr.status = %(status)s" if status else ""
    sql = f"""
        SELECT cr.id, cr.round_label, cr.round_start, cr.round_end,
               cr.agent_total_stake, cr.agent_total_prize,
               cr.agent_profit_loss, cr.agent_roi,
               cr.user_total_stake, cr.user_total_prize,
               cr.user_profit_loss, cr.user_roi,
               cr.winner, cr.status, cr.created_at, cr.updated_at
        FROM competition_rounds cr
        {where}
        ORDER BY cr.round_start DESC
        LIMIT %(limit)s
    """
    params: dict[str, Any] = {"limit": limit}
    if status:
        params["status"] = status
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_round_row(r) for r in rows]


# ── Daily stats computation ─────────────────────────────────────────

def compute_agent_daily_stats(conn: Any, target_date: date) -> dict:
    """Aggregate agent pool stats for a given date.

    Stakes from simulation_tickets created on target_date (committed capital).
    Prizes from ticket_settlements settled on target_date (realized returns).
    This correctly captures the timing: you commit capital on day N,
    and receive returns when the match settles (possibly days later).
    """
    # Stakes: tickets created today
    sql_stake = """
        SELECT
            COALESCE(SUM(st.suggested_stake), 0) AS daily_stake,
            COUNT(st.id) AS ticket_count
        FROM simulation_tickets st
        WHERE st.created_at::date = %(target_date)s
          AND st.ticket_status IN ('generated', 'activated', 'settled')
    """
    with conn.cursor() as cur:
        cur.execute(sql_stake, {"target_date": target_date})
        row = cur.fetchone()
    daily_stake = float(row[0] or 0)
    ticket_count = int(row[1] or 0)

    # Prizes: settlements created today
    sql_prize = """
        SELECT
            COALESCE(SUM(ts.prize_amount), 0) AS daily_prize,
            COALESCE(SUM(ts.profit_loss), 0) AS daily_profit_loss
        FROM ticket_settlements ts
        WHERE ts.ticket_source = 'simulation'
          AND ts.created_at::date = %(target_date)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_prize, {"target_date": target_date})
        row2 = cur.fetchone()

    daily_prize = float(row2[0] or 0)
    daily_pl = float(row2[1] or 0)
    daily_roi = (daily_pl / daily_stake) if daily_stake > 0 else 0.0

    return {
        "daily_stake": round(daily_stake, 2),
        "daily_prize": round(daily_prize, 2),
        "daily_profit_loss": round(daily_pl, 2),
        "daily_roi": round(daily_roi, 6),
        "ticket_count": ticket_count,
        "budget_usage_rate": round(daily_stake / AGENT_DAILY_BUDGET, 4) if AGENT_DAILY_BUDGET > 0 else 0.0,
    }


def compute_user_daily_stats(conn: Any, target_date: date) -> dict:
    """Aggregate user pool stats for a given date from real_tickets.

    Stakes from real_tickets.total_amount on purchase_time date.
    Prizes from ticket_settlements where ticket_source='real'.
    """
    sql = """
        SELECT
            COALESCE(SUM(rt.total_amount), 0) AS daily_stake,
            COUNT(rt.id) AS ticket_count
        FROM real_tickets rt
        WHERE rt.purchase_time::date = %(target_date)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"target_date": target_date})
        row = cur.fetchone()

    daily_stake = float(row[0] or 0)
    ticket_count = int(row[1] or 0)

    # Prizes from settlements where real tickets were settled today
    sql_prize = """
        SELECT
            COALESCE(SUM(ts.prize_amount), 0) AS daily_prize,
            COALESCE(SUM(ts.profit_loss), 0) AS daily_profit_loss
        FROM ticket_settlements ts
        WHERE ts.ticket_source = 'real'
          AND ts.created_at::date = %(target_date)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_prize, {"target_date": target_date})
        row2 = cur.fetchone()

    daily_prize = float(row2[0] or 0)
    daily_pl = float(row2[1] or 0)
    daily_roi = (daily_pl / daily_stake) if daily_stake > 0 else 0.0

    return {
        "daily_stake": round(daily_stake, 2),
        "daily_prize": round(daily_prize, 2),
        "daily_profit_loss": round(daily_pl, 2),
        "daily_roi": round(daily_roi, 6),
        "ticket_count": ticket_count,
    }


# ── Snapshot management ─────────────────────────────────────────────

def upsert_daily_snapshot(
    conn: Any,
    round_id: int,
    snapshot_date: date,
    agent: dict,
    user: dict,
    agent_cumulative_stake: float = 0.0,
    agent_cumulative_prize: float = 0.0,
    agent_cumulative_roi: float = 0.0,
    user_cumulative_stake: float = 0.0,
    user_cumulative_prize: float = 0.0,
    user_cumulative_roi: float = 0.0,
) -> dict:
    """Insert or update a daily competition snapshot.

    Idempotent: if a snapshot for (round_id, snapshot_date) already
    exists, updates it instead of creating a duplicate.
    """
    sql_upsert = """
        INSERT INTO competition_daily_snapshots (
            round_id, snapshot_date,
            agent_daily_stake, agent_daily_prize, agent_daily_profit_loss,
            agent_daily_roi, agent_cumulative_stake, agent_cumulative_prize,
            agent_cumulative_roi, agent_budget_usage_rate, agent_ticket_count,
            user_daily_stake, user_daily_prize, user_daily_profit_loss,
            user_daily_roi, user_cumulative_stake, user_cumulative_prize,
            user_cumulative_roi, user_ticket_count, created_at
        ) VALUES (
            %(round_id)s, %(snapshot_date)s,
            %(agent_daily_stake)s, %(agent_daily_prize)s, %(agent_daily_profit_loss)s,
            %(agent_daily_roi)s, %(agent_cumulative_stake)s, %(agent_cumulative_prize)s,
            %(agent_cumulative_roi)s, %(agent_budget_usage_rate)s, %(agent_ticket_count)s,
            %(user_daily_stake)s, %(user_daily_prize)s, %(user_daily_profit_loss)s,
            %(user_daily_roi)s, %(user_cumulative_stake)s, %(user_cumulative_prize)s,
            %(user_cumulative_roi)s, %(user_ticket_count)s, now()
        )
        ON CONFLICT (round_id, snapshot_date)
        DO UPDATE SET
            agent_daily_stake = EXCLUDED.agent_daily_stake,
            agent_daily_prize = EXCLUDED.agent_daily_prize,
            agent_daily_profit_loss = EXCLUDED.agent_daily_profit_loss,
            agent_daily_roi = EXCLUDED.agent_daily_roi,
            agent_cumulative_stake = EXCLUDED.agent_cumulative_stake,
            agent_cumulative_prize = EXCLUDED.agent_cumulative_prize,
            agent_cumulative_roi = EXCLUDED.agent_cumulative_roi,
            agent_budget_usage_rate = EXCLUDED.agent_budget_usage_rate,
            agent_ticket_count = EXCLUDED.agent_ticket_count,
            user_daily_stake = EXCLUDED.user_daily_stake,
            user_daily_prize = EXCLUDED.user_daily_prize,
            user_daily_profit_loss = EXCLUDED.user_daily_profit_loss,
            user_daily_roi = EXCLUDED.user_daily_roi,
            user_cumulative_stake = EXCLUDED.user_cumulative_stake,
            user_cumulative_prize = EXCLUDED.user_cumulative_prize,
            user_cumulative_roi = EXCLUDED.user_cumulative_roi,
            user_ticket_count = EXCLUDED.user_ticket_count
        RETURNING id
    """
    params = {
        "round_id": round_id,
        "snapshot_date": snapshot_date,
        "agent_daily_stake": agent.get("daily_stake", 0),
        "agent_daily_prize": agent.get("daily_prize", 0),
        "agent_daily_profit_loss": agent.get("daily_profit_loss", 0),
        "agent_daily_roi": agent.get("daily_roi", 0),
        "agent_cumulative_stake": agent_cumulative_stake,
        "agent_cumulative_prize": agent_cumulative_prize,
        "agent_cumulative_roi": agent_cumulative_roi,
        "agent_budget_usage_rate": agent.get("budget_usage_rate", 0),
        "agent_ticket_count": agent.get("ticket_count", 0),
        "user_daily_stake": user.get("daily_stake", 0),
        "user_daily_prize": user.get("daily_prize", 0),
        "user_daily_profit_loss": user.get("daily_profit_loss", 0),
        "user_daily_roi": user.get("daily_roi", 0),
        "user_cumulative_stake": user_cumulative_stake,
        "user_cumulative_prize": user_cumulative_prize,
        "user_cumulative_roi": user_cumulative_roi,
        "user_ticket_count": user.get("ticket_count", 0),
    }
    with conn.cursor() as cur:
        cur.execute(sql_upsert, params)
        row = cur.fetchone()
    conn.commit()
    return {"id": row[0] if row else None, "snapshot_date": _date_str(snapshot_date)}


def finalize_round(conn: Any, round_id: int) -> dict:
    """Finalize a competition round: compute winner and set status to 'completed'.

    Winner is determined by higher ROI. Equal ROI → 'draw'.
    """
    # Aggregate from snapshots to get final round totals
    sql_agg = """
        SELECT
            SUM(agent_daily_stake) AS agent_stake,
            SUM(agent_daily_prize) AS agent_prize,
            SUM(user_daily_stake) AS user_stake,
            SUM(user_daily_prize) AS user_prize
        FROM competition_daily_snapshots
        WHERE round_id = %(round_id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_agg, {"round_id": round_id})
        row = cur.fetchone()

    agent_stake = float(row[0] or 0)
    agent_prize = float(row[1] or 0)
    user_stake = float(row[2] or 0)
    user_prize = float(row[3] or 0)

    agent_pl = agent_prize - agent_stake
    user_pl = user_prize - user_stake
    agent_roi = (agent_pl / agent_stake) if agent_stake > 0 else 0.0
    user_roi = (user_pl / user_stake) if user_stake > 0 else 0.0

    if agent_roi > user_roi:
        winner = "agent"
    elif user_roi > agent_roi:
        winner = "user"
    else:
        winner = "draw"

    sql_update = """
        UPDATE competition_rounds SET
            agent_total_stake = %(agent_stake)s,
            agent_total_prize = %(agent_prize)s,
            agent_profit_loss = %(agent_pl)s,
            agent_roi = %(agent_roi)s,
            user_total_stake = %(user_stake)s,
            user_total_prize = %(user_prize)s,
            user_profit_loss = %(user_pl)s,
            user_roi = %(user_roi)s,
            winner = %(winner)s,
            status = 'completed',
            updated_at = now()
        WHERE id = %(round_id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_update, {
            "round_id": round_id,
            "agent_stake": agent_stake,
            "agent_prize": agent_prize,
            "agent_pl": agent_pl,
            "agent_roi": agent_roi,
            "user_stake": user_stake,
            "user_prize": user_prize,
            "user_pl": user_pl,
            "user_roi": user_roi,
            "winner": winner,
        })
    conn.commit()

    return {
        "round_id": round_id,
        "winner": winner,
        "agent_roi": round(agent_roi, 6),
        "user_roi": round(user_roi, 6),
        "agent_profit_loss": round(agent_pl, 2),
        "user_profit_loss": round(user_pl, 2),
    }


# ── Trend data ──────────────────────────────────────────────────────

def get_trend_data(conn: Any, round_id: int) -> list[dict]:
    """Get cumulative ROI trend series for chart rendering.

    Returns list of {snapshot_date, agent_cumulative_roi, user_cumulative_roi}.
    """
    sql = """
        SELECT snapshot_date,
               agent_cumulative_roi,
               user_cumulative_roi,
               agent_cumulative_stake,
               agent_cumulative_prize,
               user_cumulative_stake,
               user_cumulative_prize
        FROM competition_daily_snapshots
        WHERE round_id = %(round_id)s
        ORDER BY snapshot_date
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"round_id": round_id})
        rows = cur.fetchall()
    return [
        {
            "snapshot_date": _date_str(r[0]),
            "agent_cumulative_roi": float(r[1] or 0),
            "user_cumulative_roi": float(r[2] or 0),
            "agent_cumulative_stake": float(r[3] or 0),
            "agent_cumulative_prize": float(r[4] or 0),
            "user_cumulative_stake": float(r[5] or 0),
            "user_cumulative_prize": float(r[6] or 0),
        }
        for r in rows
    ]


# ── Summary ─────────────────────────────────────────────────────────

def get_summary(conn: Any) -> dict:
    """Get overall competition summary: total rounds, wins per side."""
    sql = """
        SELECT
            COUNT(*) AS total_rounds,
            COUNT(*) FILTER (WHERE status = 'completed') AS completed_rounds,
            COUNT(*) FILTER (WHERE winner = 'agent') AS agent_wins,
            COUNT(*) FILTER (WHERE winner = 'user') AS user_wins,
            COUNT(*) FILTER (WHERE winner = 'draw') AS draws,
            COUNT(*) FILTER (WHERE status = 'active') AS active_rounds
        FROM competition_rounds
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
    return {
        "total_rounds": row[0] or 0,
        "completed_rounds": row[1] or 0,
        "agent_wins": row[2] or 0,
        "user_wins": row[3] or 0,
        "draws": row[4] or 0,
        "active_rounds": row[5] or 0,
    }


# ── Agent bankroll ──────────────────────────────────────────────────

AGENT_INITIAL_BALANCE = AGENT_DAILY_BUDGET  # ¥500


def ensure_agent_bankroll(conn: Any) -> dict:
    """Get or create the competition_agent bankroll account.

    Returns account dict with id, current_balance, daily_budget.
    """
    sql_select = """
        SELECT id, account_type, initial_balance, current_balance,
               daily_budget, weekly_budget, monthly_budget,
               created_at, updated_at
        FROM bankroll_accounts
        WHERE account_type = 'competition_agent'
        LIMIT 1
    """
    sql_insert = """
        INSERT INTO bankroll_accounts
            (user_id, account_type, initial_balance, current_balance,
             daily_budget, weekly_budget, monthly_budget, created_at, updated_at)
        VALUES (1, 'competition_agent', %(balance)s, %(balance)s,
                %(daily_budget)s, NULL, NULL, now(), now())
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(sql_select)
        row = cur.fetchone()
        if row:
            conn.commit()
            return {
                "id": row[0],
                "account_type": row[1],
                "initial_balance": float(row[2] or 0),
                "current_balance": float(row[3] or 0),
                "daily_budget": float(row[4] or 0),
            }
        cur.execute(sql_insert, {
            "balance": AGENT_INITIAL_BALANCE,
            "daily_budget": AGENT_DAILY_BUDGET,
        })
        cur.execute(sql_select)
        row = cur.fetchone()
    conn.commit()
    if row:
        return {
            "id": row[0],
            "account_type": row[1],
            "initial_balance": float(row[2] or 0),
            "current_balance": float(row[3] or 0),
            "daily_budget": float(row[4] or 0),
        }
    return {}


def reset_agent_budget(conn: Any) -> dict:
    """Reset agent bankroll to ¥500 for the new day.

    Records a 'daily_budget_reset' transaction. Returns the previous
    balance and new balance.
    """
    account = ensure_agent_bankroll(conn)
    if not account or not account.get("id"):
        return {"status": "error", "message": "no competition_agent account"}

    account_id = account["id"]
    prev_balance = account["current_balance"]
    new_balance = AGENT_DAILY_BUDGET

    # Record reset transaction
    sql_txn = """
        INSERT INTO bankroll_transactions
            (account_id, transaction_type, amount, balance_after, remark, created_at)
        VALUES (%(account_id)s, 'daily_budget_reset', %(amount)s, %(balance_after)s,
                %(remark)s, now())
    """
    with conn.cursor() as cur:
        cur.execute(sql_txn, {
            "account_id": account_id,
            "amount": new_balance - prev_balance,
            "balance_after": new_balance,
            "remark": f"Daily reset: {prev_balance:.2f} → {new_balance:.2f}",
        })

    # Update balance
    sql_update = """
        UPDATE bankroll_accounts
        SET current_balance = %(balance)s, updated_at = now()
        WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_update, {"balance": new_balance, "id": account_id})
    conn.commit()

    return {
        "status": "ok",
        "previous_balance": round(prev_balance, 2),
        "new_balance": round(new_balance, 2),
    }
