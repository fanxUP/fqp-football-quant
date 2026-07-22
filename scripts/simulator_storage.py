"""Simulator ticket storage layer.

Follows the same psycopg2 CRUD pattern as real_ticket_storage.py.
All functions accept conn: Any and call conn.commit() internally.
"""

from __future__ import annotations

from typing import Any

INITIAL_SIMULATOR_BALANCE = 100_000.00  # 初始虚拟资金 10万元

# ---- Row dict helpers ----

def _account_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "account_type": r[1],
        "initial_balance": float(r[2]) if r[2] else 0.0,
        "current_balance": float(r[3]) if r[3] else 0.0,
        "daily_budget": float(r[4]) if r[4] else 0.0,
        "weekly_budget": float(r[5]) if r[5] else None,
        "monthly_budget": float(r[6]) if r[6] else None,
        "created_at": _iso(r[7]),
        "updated_at": _iso(r[8]),
    }


def _txn_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "account_id": r[1],
        "transaction_type": r[2],
        "amount": float(r[3]) if r[3] else 0.0,
        "related_ticket_id": r[4],
        "balance_after": float(r[5]) if r[5] else 0.0,
        "transaction_time": _iso(r[6]),
        "remark": r[7],
        "created_at": _iso(r[8]),
    }


def _ticket_row(trow: tuple, irows: list) -> dict:
    return {
        "id": trow[0],
        "play_type": trow[1],
        "pass_type": trow[2],
        "multiple": trow[3],
        "total_cost": float(trow[4]) if trow[4] else 0.0,
        "bet_count": trow[5],
        "max_prize": float(trow[6]) if trow[6] else 0.0,
        "match_count": trow[7],
        "status": trow[8],
        "notes": trow[9],
        "created_at": _iso(trow[10]),
        "updated_at": _iso(trow[11]),
        "ledger_ticket_no": trow[12],
        "items": [_item_row(r) for r in irows],
    }


def _item_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "ticket_id": r[1],
        "match_id": r[2],
        "play_type": r[3],
        "option_code": r[4],
        "option_name": r[5],
        "sp_value": float(r[6]) if r[6] else 0.0,
        "handicap": float(r[7]) if r[7] else None,
        "is_dan": r[8],
        "created_at": _iso(r[9]),
        "home_team_name": r[10] if len(r) > 10 else None,
        "away_team_name": r[11] if len(r) > 11 else None,
        "league_name": r[12] if len(r) > 12 else None,
        "kickoff_time": _iso(r[13]) if len(r) > 13 else None,
    }


def _summary_row(r: tuple) -> dict:
    return {
        "id": r[0],
        "play_type": r[1],
        "pass_type": r[2],
        "multiple": r[3],
        "total_cost": float(r[4]) if r[4] else 0.0,
        "bet_count": r[5],
        "max_prize": float(r[6]) if r[6] else 0.0,
        "match_count": r[7],
        "status": r[8],
        "notes": r[9],
        "created_at": _iso(r[10]),
        "updated_at": _iso(r[11]),
        "item_count": r[12],
        "ledger_ticket_no": r[13],
    }


def _iso(val) -> str | None:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


# ---- Bankroll (account_type = 'simulator') ----

def ensure_simulator_bankroll(conn: Any) -> dict:
    """Get or create the simulator bankroll account. Returns account dict."""
    sql_select = """
        SELECT id, account_type, initial_balance, current_balance,
               daily_budget, weekly_budget, monthly_budget,
               created_at, updated_at
        FROM bankroll_accounts
        WHERE account_type = 'simulator'
        LIMIT 1
    """
    sql_insert = """
        INSERT INTO bankroll_accounts
            (user_id, account_type, initial_balance, current_balance,
             daily_budget, weekly_budget, monthly_budget, created_at, updated_at)
        VALUES (1, 'simulator', %(balance)s, %(balance)s,
                NULL, NULL, NULL, now(), now())
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(sql_select)
        row = cur.fetchone()
        if row:
            conn.commit()
            return _account_row(row)

        cur.execute(sql_insert, {"balance": INITIAL_SIMULATOR_BALANCE})
        cur.execute(sql_select)
        row = cur.fetchone()
    conn.commit()
    return _account_row(row)


def get_bankroll_summary(conn: Any) -> dict:
    """Return balance + aggregate stats for simulator account.

    Does NOT create the account — reads only. Returns a zeroed summary
    when no simulator account exists yet.
    """
    sql_account = """
        SELECT id, account_type, initial_balance, current_balance,
               daily_budget, weekly_budget, monthly_budget,
               created_at, updated_at
        FROM bankroll_accounts
        WHERE account_type = 'simulator'
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql_account)
        row = cur.fetchone()

    if not row:
        return {
            "account_id": None,
            "initial_balance": INITIAL_SIMULATOR_BALANCE,
            "current_balance": INITIAL_SIMULATOR_BALANCE,
            "total_staked": 0,
            "total_won": 0,
            "profit_loss": 0,
            "roi": 0,
        }

    account = _account_row(row)
    sql = """
        SELECT
            COALESCE(SUM(CASE WHEN transaction_type = 'stake' THEN ABS(amount) ELSE 0 END), 0) AS total_staked,
            COALESCE(SUM(CASE WHEN transaction_type = 'prize' THEN amount ELSE 0 END), 0) AS total_won
        FROM bankroll_transactions
        WHERE account_id = %(account_id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"account_id": account["id"]})
        txn_row = cur.fetchone()
    total_staked = float(txn_row[0] or 0)
    total_won = float(txn_row[1] or 0)
    pnl = total_won - total_staked
    roi = (pnl / total_staked) if total_staked > 0 else 0.0
    return {
        "account_id": account["id"],
        "initial_balance": account["initial_balance"],
        "current_balance": account["current_balance"],
        "total_staked": round(total_staked, 2),
        "total_won": round(total_won, 2),
        "profit_loss": round(pnl, 2),
        "roi": round(roi, 4),
    }


def list_bankroll_transactions(conn: Any, limit: int = 50) -> list[dict]:
    """List recent transactions for the simulator account."""
    sql = """
        SELECT bt.id, bt.account_id, bt.transaction_type, bt.amount,
               bt.related_ticket_id, bt.balance_after, bt.transaction_time,
               bt.remark, bt.created_at
        FROM bankroll_transactions bt
        JOIN bankroll_accounts ba ON ba.id = bt.account_id
        WHERE ba.account_type = 'simulator'
        ORDER BY bt.created_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"limit": limit})
        rows = cur.fetchall()
    return [_txn_row(r) for r in rows]


def reset_bankroll(conn: Any) -> dict:
    """Reset simulator bankroll to initial balance. Deletes all related transactions."""
    sql_select = "SELECT id FROM bankroll_accounts WHERE account_type = 'simulator' LIMIT 1"
    sql_delete_txn = "DELETE FROM bankroll_transactions WHERE account_id = %(id)s"
    sql_update = """
        UPDATE bankroll_accounts SET current_balance = %(balance)s, updated_at = now()
        WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_select)
        row = cur.fetchone()
        if not row:
            conn.commit()
            return {"status": "ok", "note": "no account found"}
        account_id = row[0]
        cur.execute(sql_delete_txn, {"id": account_id})
        cur.execute(sql_update, {"balance": INITIAL_SIMULATOR_BALANCE, "id": account_id})
    conn.commit()
    return {"status": "ok", "balance": INITIAL_SIMULATOR_BALANCE}


# ---- Simulator Tickets ----

def create_simulator_ticket(conn: Any, ticket: dict) -> int | None:
    """Insert a simulator ticket. Returns the new ticket id."""
    sql = """
        INSERT INTO simulator_tickets (
            play_type, pass_type, multiple, total_cost, bet_count,
            max_prize, match_count, status, notes, created_at, updated_at
        ) VALUES (
            %(play_type)s, %(pass_type)s, %(multiple)s, %(total_cost)s,
            %(bet_count)s, %(max_prize)s, %(match_count)s, %(status)s,
            %(notes)s, now(), now()
        )
        RETURNING id
    """
    params = {
        "play_type": ticket.get("play_type", "spf"),
        "pass_type": ticket.get("pass_type", "single"),
        "multiple": ticket.get("multiple", 1),
        "total_cost": ticket.get("total_cost", 0),
        "bet_count": ticket.get("bet_count", 1),
        "max_prize": ticket.get("max_prize", 0),
        "match_count": ticket.get("match_count", 0),
        "status": ticket.get("status", "pending"),
        "notes": ticket.get("notes", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def create_simulator_items_batch(conn: Any, ticket_id: int, items: list[dict]) -> list[int]:
    """Batch-insert items for a simulator ticket. Returns list of new item ids."""
    sql = """
        INSERT INTO simulator_ticket_items (
            ticket_id, match_id, play_type, option_code, option_name,
            sp_value, handicap, is_dan, created_at
        ) VALUES (
            %(ticket_id)s, %(match_id)s, %(play_type)s, %(option_code)s,
            %(option_name)s, %(sp_value)s, %(handicap)s, %(is_dan)s, now()
        )
        RETURNING id
    """
    ids = []
    with conn.cursor() as cur:
        for item in items:
            params = {
                "ticket_id": ticket_id,
                "match_id": item.get("match_id"),
                "play_type": item.get("play_type"),
                "option_code": item.get("option_code"),
                "option_name": item.get("option_name"),
                "sp_value": item.get("sp_value", 0),
                "handicap": item.get("handicap"),
                "is_dan": item.get("is_dan", False),
            }
            cur.execute(sql, params)
            row = cur.fetchone()
            if row:
                ids.append(row[0])
    conn.commit()
    return ids


def get_simulator_ticket(conn: Any, ticket_id: int) -> dict | None:
    """Get a single simulator ticket with its items (joined with match info)."""
    sql_ticket = """
        SELECT id, play_type, pass_type, multiple, total_cost, bet_count,
               max_prize, match_count, status, notes, created_at, updated_at,
               ledger_ticket_no
        FROM simulator_tickets WHERE id = %(id)s
    """
    sql_items = """
        SELECT sti.id, sti.ticket_id, sti.match_id, sti.play_type,
               sti.option_code, sti.option_name, sti.sp_value,
               sti.handicap, sti.is_dan, sti.created_at,
               m.home_team_name, m.away_team_name,
               m.league_name, m.kickoff_time
        FROM simulator_ticket_items sti
        JOIN official_matches m ON m.id = sti.match_id
        WHERE sti.ticket_id = %(ticket_id)s
        ORDER BY sti.id
    """
    with conn.cursor() as cur:
        cur.execute(sql_ticket, {"id": ticket_id})
        trow = cur.fetchone()
        if not trow:
            return None
        cur.execute(sql_items, {"ticket_id": ticket_id})
        irows = cur.fetchall()
    return _ticket_row(trow, irows)


def list_simulator_tickets(
    conn: Any, status: str | None = None, limit: int = 20, offset: int = 0
) -> list[dict]:
    """List simulator tickets, optionally filtered by status."""
    where = "WHERE st.status = %(status)s" if status else ""
    sql = f"""
        SELECT st.id, st.play_type, st.pass_type, st.multiple, st.total_cost,
               st.bet_count, st.max_prize, st.match_count, st.status,
               st.notes, st.created_at, st.updated_at,
               COUNT(sti.id) AS item_count, st.ledger_ticket_no
        FROM simulator_tickets st
        LEFT JOIN simulator_ticket_items sti ON sti.ticket_id = st.id
        {where}
        GROUP BY st.id
        ORDER BY st.created_at DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_summary_row(r) for r in rows]


def delete_simulator_ticket(conn: Any, ticket_id: int) -> bool:
    """Cancel a pending simulator ticket. Items are cascade-deleted via FK ON DELETE CASCADE."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM simulator_tickets WHERE id = %(id)s", {"id": ticket_id})
        ok = cur.rowcount > 0
    conn.commit()
    return ok


def update_ticket_status(conn: Any, ticket_id: int, status: str) -> bool:
    """Update ticket status (pending -> settled / cancelled)."""
    sql = "UPDATE simulator_tickets SET status = %(status)s, updated_at = now() WHERE id = %(id)s"
    with conn.cursor() as cur:
        cur.execute(sql, {"status": status, "id": ticket_id})
        ok = cur.rowcount > 0
    conn.commit()
    return ok
