"""Stage 5 storage layer: real tickets, settlements, reviews, error analysis.

Follows the same psycopg2 CRUD pattern as model_storage.py and official_storage.py.
All functions accept conn: Any and call conn.commit() internally.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Audit log (shared utility)
# ---------------------------------------------------------------------------


def _audit_log(
    conn: Any,
    action_type: str,
    target_table: str,
    target_id: int,
    before: dict | None = None,
    after: dict | None = None,
) -> int | None:
    """Write an audit log entry. Non-blocking — failures are silent."""
    try:
        sql = """
            INSERT INTO audit_logs (user_id, action_type, target_table, target_id,
                                    before_json, after_json, created_at)
            VALUES (1, %(action_type)s, %(target_table)s, %(target_id)s,
                    %(before_json)s, %(after_json)s, now())
            RETURNING id
        """
        with conn.cursor() as cur:
            cur.execute(
                sql,
                {
                    "action_type": action_type,
                    "target_table": target_table,
                    "target_id": target_id,
                    "before_json": json.dumps(before, ensure_ascii=False) if before else None,
                    "after_json": json.dumps(after, ensure_ascii=False) if after else None,
                },
            )
            row = cur.fetchone()
        conn.commit()
        return row[0] if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Real tickets
# ---------------------------------------------------------------------------


def create_real_ticket(conn: Any, ticket: dict) -> int | None:
    """Insert a real ticket. Returns the new ticket id."""
    sql = """
        INSERT INTO real_tickets (
            user_id, related_simulation_ticket_id, ticket_image_url,
            ticket_no, purchase_time, store_code, total_amount, multiple,
            pass_type, theoretical_max_prize, source_type,
            ocr_status, confirm_status, settlement_status,
            created_at, updated_at
        ) VALUES (
            1, %(related_simulation_ticket_id)s, %(ticket_image_url)s,
            %(ticket_no)s, %(purchase_time)s, %(store_code)s,
            %(total_amount)s, %(multiple)s, %(pass_type)s,
            %(theoretical_max_prize)s, %(source_type)s,
            %(ocr_status)s, %(confirm_status)s, %(settlement_status)s,
            now(), now()
        )
        RETURNING id
    """
    params = {
        "related_simulation_ticket_id": ticket.get("related_simulation_ticket_id"),
        "ticket_image_url": ticket.get("ticket_image_url"),
        "ticket_no": ticket.get("ticket_no"),
        "purchase_time": ticket.get("purchase_time", _now()),
        "store_code": ticket.get("store_code"),
        "total_amount": ticket.get("total_amount", 0),
        "multiple": ticket.get("multiple", 1),
        "pass_type": ticket.get("pass_type", "single"),
        "theoretical_max_prize": ticket.get("theoretical_max_prize"),
        "source_type": ticket.get("source_type", "manual_entry"),
        "ocr_status": ticket.get("ocr_status", "not_applicable"),
        "confirm_status": ticket.get("confirm_status", "confirmed"),
        "settlement_status": ticket.get("settlement_status", "pending"),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def update_real_ticket(conn: Any, ticket_id: int, updates: dict) -> bool:
    """Update a real ticket's mutable fields."""
    allowed = {
        "related_simulation_ticket_id",
        "ticket_image_url",
        "ticket_no",
        "confirm_status",
        "settlement_status",
        "total_amount",
        "theoretical_max_prize",
        "purchase_time",
    }
    filtered = {k: v for k, v in updates.items() if k in allowed}
    if not filtered:
        return False

    set_clauses = [f"{k} = %({k})s" for k in filtered]
    filtered["id"] = ticket_id

    sql = f"UPDATE real_tickets SET {', '.join(set_clauses)}, updated_at = now() WHERE id = %(id)s"
    with conn.cursor() as cur:
        cur.execute(sql, filtered)
        ok = cur.rowcount > 0
    conn.commit()

    if ok:
        _audit_log(conn, "update", "real_tickets", ticket_id, after=updates)
    return ok


def get_real_ticket(conn: Any, ticket_id: int) -> dict | None:
    """Get a single real ticket with item count."""
    sql = """
        SELECT rt.id, rt.user_id, rt.related_simulation_ticket_id,
               rt.ticket_image_url, rt.ticket_no, rt.purchase_time,
               rt.store_code, rt.total_amount, rt.multiple, rt.pass_type,
               rt.theoretical_max_prize, rt.source_type,
               rt.ocr_status, rt.confirm_status, rt.settlement_status,
               rt.created_at, rt.updated_at,
               COUNT(rti.id) AS item_count
        FROM real_tickets rt
        LEFT JOIN real_ticket_items rti ON rti.real_ticket_id = rt.id
        WHERE rt.id = %(id)s
        GROUP BY rt.id
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"id": ticket_id})
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "related_simulation_ticket_id": row[2],
        "ticket_image_url": row[3],
        "ticket_no": row[4],
        "purchase_time": row[5].isoformat()
        if hasattr(row[5], "isoformat")
        else str(row[5])
        if row[5]
        else None,
        "store_code": row[6],
        "total_amount": float(row[7]) if row[7] else 0,
        "multiple": row[8],
        "pass_type": row[9],
        "theoretical_max_prize": float(row[10]) if row[10] else None,
        "source_type": row[11],
        "ocr_status": row[12],
        "confirm_status": row[13],
        "settlement_status": row[14],
        "created_at": row[15].isoformat()
        if hasattr(row[15], "isoformat")
        else str(row[15])
        if row[15]
        else None,
        "updated_at": row[16].isoformat()
        if hasattr(row[16], "isoformat")
        else str(row[16])
        if row[16]
        else None,
        "item_count": row[17],
    }


def list_real_tickets(conn: Any, status: str | None = None, limit: int = 20) -> list[dict]:
    """List real tickets, optionally filtered by settlement_status."""
    if status:
        sql = """
            SELECT rt.id, rt.pass_type, rt.total_amount, rt.multiple,
                   rt.theoretical_max_prize, rt.source_type, rt.ocr_status,
                   rt.confirm_status, rt.settlement_status,
                   rt.purchase_time, rt.created_at,
                   rt.related_simulation_ticket_id,
                   COUNT(rti.id) AS item_count
            FROM real_tickets rt
            LEFT JOIN real_ticket_items rti ON rti.real_ticket_id = rt.id
            WHERE rt.settlement_status = %(status)s
            GROUP BY rt.id
            ORDER BY rt.created_at DESC LIMIT %(limit)s
        """
        params = {"status": status, "limit": limit}
    else:
        sql = """
            SELECT rt.id, rt.pass_type, rt.total_amount, rt.multiple,
                   rt.theoretical_max_prize, rt.source_type, rt.ocr_status,
                   rt.confirm_status, rt.settlement_status,
                   rt.purchase_time, rt.created_at,
                   rt.related_simulation_ticket_id,
                   COUNT(rti.id) AS item_count
            FROM real_tickets rt
            LEFT JOIN real_ticket_items rti ON rti.real_ticket_id = rt.id
            GROUP BY rt.id
            ORDER BY rt.created_at DESC LIMIT %(limit)s
        """
        params = {"limit": limit}

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "pass_type": r[1],
            "total_amount": float(r[2]) if r[2] else 0,
            "multiple": r[3],
            "theoretical_max_prize": float(r[4]) if r[4] else None,
            "source_type": r[5],
            "ocr_status": r[6],
            "confirm_status": r[7],
            "settlement_status": r[8],
            "purchase_time": r[9].isoformat()
            if hasattr(r[9], "isoformat")
            else str(r[9])
            if r[9]
            else None,
            "created_at": r[10].isoformat()
            if hasattr(r[10], "isoformat")
            else str(r[10])
            if r[10]
            else None,
            "related_simulation_ticket_id": r[11],
            "item_count": r[12],
        }
        for r in rows
    ]


def delete_real_ticket(conn: Any, ticket_id: int) -> bool:
    """Delete a real ticket and its items (cascade)."""
    before = get_real_ticket(conn, ticket_id)
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM real_ticket_items WHERE real_ticket_id = %(id)s", {"id": ticket_id}
        )
        cur.execute("DELETE FROM real_tickets WHERE id = %(id)s", {"id": ticket_id})
        ok = cur.rowcount > 0
    conn.commit()
    if ok:
        _audit_log(conn, "delete", "real_tickets", ticket_id, before=before)
    return ok


# ---------------------------------------------------------------------------
# Real ticket items
# ---------------------------------------------------------------------------


def create_real_ticket_items_batch(conn: Any, ticket_id: int, items: list[dict]) -> list[int]:
    """Batch-insert items for a real ticket. Returns list of new item ids."""
    sql = """
        INSERT INTO real_ticket_items (
            real_ticket_id, match_id, official_match_code,
            play_type, option_code, option_name, sp_value,
            is_matched_with_model, deviation_type, created_at
        ) VALUES (
            %(real_ticket_id)s, %(match_id)s, %(official_match_code)s,
            %(play_type)s, %(option_code)s, %(option_name)s, %(sp_value)s,
            %(is_matched_with_model)s, %(deviation_type)s, now()
        )
        RETURNING id
    """
    ids = []
    with conn.cursor() as cur:
        for item in items:
            params = {
                "real_ticket_id": ticket_id,
                "match_id": item.get("match_id"),
                "official_match_code": item.get("official_match_code"),
                "play_type": item.get("play_type", "spf"),
                "option_code": item.get("option_code"),
                "option_name": item.get("option_name"),
                "sp_value": item.get("sp_value", 0),
                "is_matched_with_model": item.get("is_matched_with_model", False),
                "deviation_type": item.get("deviation_type"),
            }
            cur.execute(sql, params)
            row = cur.fetchone()
            if row:
                ids.append(row[0])
    conn.commit()
    return ids


def list_real_ticket_items(conn: Any, ticket_id: int) -> list[dict]:
    """List items for a real ticket, joined with match info."""
    sql = """
        SELECT rti.id, rti.real_ticket_id, rti.match_id,
               rti.official_match_code, rti.play_type, rti.option_code,
               rti.option_name, rti.sp_value,
               rti.is_matched_with_model, rti.deviation_type,
               rti.created_at,
               m.home_team_name, m.away_team_name
        FROM real_ticket_items rti
        LEFT JOIN official_matches m ON m.id = rti.match_id
        WHERE rti.real_ticket_id = %(ticket_id)s
        ORDER BY rti.id
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"ticket_id": ticket_id})
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "real_ticket_id": r[1],
            "match_id": r[2],
            "official_match_code": r[3],
            "play_type": r[4],
            "option_code": r[5],
            "option_name": r[6],
            "sp_value": float(r[7]) if r[7] else 0,
            "is_matched_with_model": r[8],
            "deviation_type": r[9],
            "created_at": r[10].isoformat()
            if hasattr(r[10], "isoformat")
            else str(r[10])
            if r[10]
            else None,
            "home_team_name": r[11],
            "away_team_name": r[12],
        }
        for r in rows
    ]


def update_item_model_match(
    conn: Any, item_id: int, is_matched: bool, deviation: str | None = None
) -> bool:
    """Update an item's model-matching status."""
    sql = """
        UPDATE real_ticket_items
        SET is_matched_with_model = %(is_matched)s,
            deviation_type = %(deviation)s
        WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"is_matched": is_matched, "deviation": deviation, "id": item_id})
        ok = cur.rowcount > 0
    conn.commit()
    return ok


# ---------------------------------------------------------------------------
# Ticket settlements
# ---------------------------------------------------------------------------


def create_settlement(conn: Any, settlement: dict) -> int | None:
    """Insert a ticket settlement. Idempotent — skips if already exists."""
    sql_check = """
        SELECT id FROM ticket_settlements
        WHERE ticket_source = %(ticket_source)s AND ticket_id = %(ticket_id)s
    """
    sql_insert = """
        INSERT INTO ticket_settlements (
            ticket_source, ticket_id, settle_time, is_won,
            stake_amount, prize_amount, tax_amount, net_prize,
            profit_loss, roi, settlement_detail_json, created_at
        ) VALUES (
            %(ticket_source)s, %(ticket_id)s, %(settle_time)s, %(is_won)s,
            %(stake_amount)s, %(prize_amount)s, %(tax_amount)s, %(net_prize)s,
            %(profit_loss)s, %(roi)s, %(settlement_detail_json)s, now()
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql_check,
            {
                "ticket_source": settlement["ticket_source"],
                "ticket_id": settlement["ticket_id"],
            },
        )
        existing = cur.fetchone()
        if existing:
            return existing[0]  # already settled, return existing id

        params = {
            "ticket_source": settlement["ticket_source"],
            "ticket_id": settlement["ticket_id"],
            "settle_time": settlement.get("settle_time", _now()),
            "is_won": settlement.get("is_won", False),
            "stake_amount": settlement.get("stake_amount", 0),
            "prize_amount": settlement.get("prize_amount", 0),
            "tax_amount": settlement.get("tax_amount", 0),
            "net_prize": settlement.get("net_prize", 0),
            "profit_loss": settlement.get("profit_loss", 0),
            "roi": settlement.get("roi", 0),
            "settlement_detail_json": json.dumps(
                settlement.get("settlement_detail_json", {}), ensure_ascii=False
            ),
        }
        cur.execute(sql_insert, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_settlements_by_date(conn: Any, date_str: str, source: str | None = None) -> list[dict]:
    """List settlements for a given date, optionally filtered by source."""
    if source:
        sql = """
            SELECT ts.id, ts.ticket_source, ts.ticket_id, ts.settle_time,
                   ts.is_won, ts.stake_amount, ts.prize_amount, ts.tax_amount,
                   ts.net_prize, ts.profit_loss, ts.roi, ts.settlement_detail_json
            FROM ticket_settlements ts
            WHERE (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %(date)s
              AND ts.ticket_source = %(source)s
            ORDER BY ts.settle_time DESC
        """
        params = {"date": date_str, "source": source}
    else:
        sql = """
            SELECT ts.id, ts.ticket_source, ts.ticket_id, ts.settle_time,
                   ts.is_won, ts.stake_amount, ts.prize_amount, ts.tax_amount,
                   ts.net_prize, ts.profit_loss, ts.roi, ts.settlement_detail_json
            FROM ticket_settlements ts
            WHERE (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %(date)s
            ORDER BY ts.settle_time DESC
        """
        params = {"date": date_str}

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "ticket_source": r[1],
            "ticket_id": r[2],
            "settle_time": r[3].isoformat()
            if hasattr(r[3], "isoformat")
            else str(r[3])
            if r[3]
            else None,
            "is_won": r[4],
            "stake_amount": float(r[5]) if r[5] else 0,
            "prize_amount": float(r[6]) if r[6] else 0,
            "tax_amount": float(r[7]) if r[7] else 0,
            "net_prize": float(r[8]) if r[8] else 0,
            "profit_loss": float(r[9]) if r[9] else 0,
            "roi": float(r[10]) if r[10] else 0,
            "settlement_detail_json": r[11],
        }
        for r in rows
    ]


def get_settlement_summary(conn: Any, date_str: str) -> dict:
    """Aggregate settlement data for a date, grouped by source."""
    sql = """
        SELECT ticket_source,
               COUNT(*) AS count,
               SUM(stake_amount) AS total_stake,
               SUM(prize_amount) AS total_prize,
               SUM(profit_loss) AS total_pl,
               AVG(roi) AS avg_roi
        FROM ticket_settlements
        WHERE (settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %(date)s
        GROUP BY ticket_source
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"date": date_str})
        rows = cur.fetchall()

    summary: dict[str, Any] = {"date": date_str, "sources": {}, "total_settled": 0}
    for r in rows:
        summary["sources"][str(r[0])] = {
            "count": r[1],
            "total_stake": float(r[2]) if r[2] else 0,
            "total_prize": float(r[3]) if r[3] else 0,
            "total_profit_loss": float(r[4]) if r[4] else 0,
            "avg_roi": float(r[5]) if r[5] else 0,
        }
        summary["total_settled"] += r[1]
    return summary


# ---------------------------------------------------------------------------
# Daily reviews
# ---------------------------------------------------------------------------


def upsert_daily_review(conn: Any, review: dict) -> int | None:
    """Insert or update a daily review. Returns the review id."""
    sql = """
        INSERT INTO daily_reviews (
            review_date, official_match_count, analyzable_match_count,
            recommended_match_count, simulation_ticket_count, real_ticket_count,
            suggested_stake, actual_stake,
            simulation_prize, real_prize,
            simulation_profit_loss, real_profit_loss,
            simulation_roi, real_roi,
            budget_usage_rate,
            max_single_ticket_loss, max_single_match_exposure,
            summary_text, next_day_adjustment, created_at
        ) VALUES (
            %(review_date)s, %(official_match_count)s, %(analyzable_match_count)s,
            %(recommended_match_count)s, %(simulation_ticket_count)s, %(real_ticket_count)s,
            %(suggested_stake)s, %(actual_stake)s,
            %(simulation_prize)s, %(real_prize)s,
            %(simulation_profit_loss)s, %(real_profit_loss)s,
            %(simulation_roi)s, %(real_roi)s,
            %(budget_usage_rate)s,
            %(max_single_ticket_loss)s, %(max_single_match_exposure)s,
            %(summary_text)s, %(next_day_adjustment)s, now()
        )
        ON CONFLICT (review_date) DO UPDATE SET
            official_match_count = EXCLUDED.official_match_count,
            analyzable_match_count = EXCLUDED.analyzable_match_count,
            recommended_match_count = EXCLUDED.recommended_match_count,
            simulation_ticket_count = EXCLUDED.simulation_ticket_count,
            real_ticket_count = EXCLUDED.real_ticket_count,
            suggested_stake = EXCLUDED.suggested_stake,
            actual_stake = EXCLUDED.actual_stake,
            simulation_prize = EXCLUDED.simulation_prize,
            real_prize = EXCLUDED.real_prize,
            simulation_profit_loss = EXCLUDED.simulation_profit_loss,
            real_profit_loss = EXCLUDED.real_profit_loss,
            simulation_roi = EXCLUDED.simulation_roi,
            real_roi = EXCLUDED.real_roi,
            budget_usage_rate = EXCLUDED.budget_usage_rate,
            max_single_ticket_loss = EXCLUDED.max_single_ticket_loss,
            max_single_match_exposure = EXCLUDED.max_single_match_exposure,
            summary_text = EXCLUDED.summary_text,
            next_day_adjustment = EXCLUDED.next_day_adjustment
        RETURNING id
    """
    params = {
        "review_date": review["review_date"],
        "official_match_count": review.get("official_match_count", 0),
        "analyzable_match_count": review.get("analyzable_match_count", 0),
        "recommended_match_count": review.get("recommended_match_count", 0),
        "simulation_ticket_count": review.get("simulation_ticket_count", 0),
        "real_ticket_count": review.get("real_ticket_count", 0),
        "suggested_stake": review.get("suggested_stake", 0),
        "actual_stake": review.get("actual_stake", 0),
        "simulation_prize": review.get("simulation_prize", 0),
        "real_prize": review.get("real_prize", 0),
        "simulation_profit_loss": review.get("simulation_profit_loss", 0),
        "real_profit_loss": review.get("real_profit_loss", 0),
        "simulation_roi": review.get("simulation_roi", 0),
        "real_roi": review.get("real_roi", 0),
        "budget_usage_rate": review.get("budget_usage_rate", 0),
        "max_single_ticket_loss": review.get("max_single_ticket_loss", 0),
        "max_single_match_exposure": review.get("max_single_match_exposure", 0),
        "summary_text": review.get("summary_text", ""),
        "next_day_adjustment": review.get("next_day_adjustment", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_daily_review(conn: Any, review_date: str) -> dict | None:
    """Get a specific daily review."""
    sql = "SELECT * FROM daily_reviews WHERE review_date = %(date)s"
    with conn.cursor() as cur:
        cur.execute(sql, {"date": review_date})
        row = cur.fetchone()
    if not row:
        return None
    return _daily_review_row_to_dict(row)


def list_daily_reviews(conn: Any, limit: int = 30) -> list[dict]:
    """List daily reviews, newest first."""
    sql = "SELECT * FROM daily_reviews ORDER BY review_date DESC LIMIT %(limit)s"
    with conn.cursor() as cur:
        cur.execute(sql, {"limit": limit})
        rows = cur.fetchall()
    return [_daily_review_row_to_dict(r) for r in rows]


def _daily_review_row_to_dict(row: tuple) -> dict:
    """Convert a daily_reviews row to a dict."""
    return {
        "id": row[0],
        "review_date": row[1].isoformat() if hasattr(row[1], "isoformat") else str(row[1]),
        "official_match_count": row[2],
        "analyzable_match_count": row[3],
        "recommended_match_count": row[4],
        "simulation_ticket_count": row[5],
        "real_ticket_count": row[6],
        "suggested_stake": float(row[7]) if row[7] else 0,
        "actual_stake": float(row[8]) if row[8] else 0,
        "simulation_prize": float(row[9]) if row[9] else 0,
        "real_prize": float(row[10]) if row[10] else 0,
        "simulation_profit_loss": float(row[11]) if row[11] else 0,
        "real_profit_loss": float(row[12]) if row[12] else 0,
        "simulation_roi": float(row[13]) if row[13] else 0,
        "real_roi": float(row[14]) if row[14] else 0,
        "budget_usage_rate": float(row[15]) if row[15] else 0,
        "max_single_ticket_loss": float(row[16]) if row[16] else 0,
        "max_single_match_exposure": float(row[17]) if row[17] else 0,
        "summary_text": row[18],
        "next_day_adjustment": row[19],
        "created_at": row[20].isoformat()
        if hasattr(row[20], "isoformat")
        else str(row[20])
        if row[20]
        else None,
    }


# ---------------------------------------------------------------------------
# Weekly reviews
# ---------------------------------------------------------------------------


def upsert_weekly_review(conn: Any, review: dict) -> int | None:
    """Insert or update a weekly review. Returns the review id."""
    sql = """
        INSERT INTO weekly_reviews (
            week_start, week_end, total_stake, total_prize,
            profit_loss, roi, max_drawdown,
            best_play_type, worst_play_type,
            best_league, worst_league,
            strategy_adjustment, created_at
        ) VALUES (
            %(week_start)s, %(week_end)s, %(total_stake)s, %(total_prize)s,
            %(profit_loss)s, %(roi)s, %(max_drawdown)s,
            %(best_play_type)s, %(worst_play_type)s,
            %(best_league)s, %(worst_league)s,
            %(strategy_adjustment)s, now()
        )
        ON CONFLICT (week_start, week_end) DO UPDATE SET
            total_stake = EXCLUDED.total_stake,
            total_prize = EXCLUDED.total_prize,
            profit_loss = EXCLUDED.profit_loss,
            roi = EXCLUDED.roi,
            max_drawdown = EXCLUDED.max_drawdown,
            best_play_type = EXCLUDED.best_play_type,
            worst_play_type = EXCLUDED.worst_play_type,
            best_league = EXCLUDED.best_league,
            worst_league = EXCLUDED.worst_league,
            strategy_adjustment = EXCLUDED.strategy_adjustment
        RETURNING id
    """
    params = {
        "week_start": review["week_start"],
        "week_end": review["week_end"],
        "total_stake": review.get("total_stake", 0),
        "total_prize": review.get("total_prize", 0),
        "profit_loss": review.get("profit_loss", 0),
        "roi": review.get("roi", 0),
        "max_drawdown": review.get("max_drawdown", 0),
        "best_play_type": review.get("best_play_type"),
        "worst_play_type": review.get("worst_play_type"),
        "best_league": review.get("best_league"),
        "worst_league": review.get("worst_league"),
        "strategy_adjustment": review.get("strategy_adjustment", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def list_weekly_reviews(conn: Any, limit: int = 12) -> list[dict]:
    """List weekly reviews, newest first."""
    sql = "SELECT * FROM weekly_reviews ORDER BY week_start DESC LIMIT %(limit)s"
    with conn.cursor() as cur:
        cur.execute(sql, {"limit": limit})
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "week_start": r[1].isoformat() if hasattr(r[1], "isoformat") else str(r[1]),
            "week_end": r[2].isoformat() if hasattr(r[2], "isoformat") else str(r[2]),
            "total_stake": float(r[3]) if r[3] else 0,
            "total_prize": float(r[4]) if r[4] else 0,
            "profit_loss": float(r[5]) if r[5] else 0,
            "roi": float(r[6]) if r[6] else 0,
            "max_drawdown": float(r[7]) if r[7] else 0,
            "best_play_type": r[8],
            "worst_play_type": r[9],
            "best_league": r[10],
            "worst_league": r[11],
            "strategy_adjustment": r[12],
            "created_at": r[13].isoformat()
            if hasattr(r[13], "isoformat")
            else str(r[13])
            if r[13]
            else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Monthly reviews
# ---------------------------------------------------------------------------


def upsert_monthly_review(conn: Any, review: dict) -> int | None:
    """Insert or update a monthly review. Returns the review id."""
    sql = """
        INSERT INTO monthly_reviews (
            month, total_stake, total_prize, profit_loss, roi,
            max_drawdown, longest_losing_streak,
            best_strategy_pool, worst_strategy_pool,
            model_calibration_score, summary_text, next_month_plan, created_at
        ) VALUES (
            %(month)s, %(total_stake)s, %(total_prize)s, %(profit_loss)s, %(roi)s,
            %(max_drawdown)s, %(longest_losing_streak)s,
            %(best_strategy_pool)s, %(worst_strategy_pool)s,
            %(model_calibration_score)s, %(summary_text)s, %(next_month_plan)s, now()
        )
        ON CONFLICT (month) DO UPDATE SET
            total_stake = EXCLUDED.total_stake,
            total_prize = EXCLUDED.total_prize,
            profit_loss = EXCLUDED.profit_loss,
            roi = EXCLUDED.roi,
            max_drawdown = EXCLUDED.max_drawdown,
            longest_losing_streak = EXCLUDED.longest_losing_streak,
            best_strategy_pool = EXCLUDED.best_strategy_pool,
            worst_strategy_pool = EXCLUDED.worst_strategy_pool,
            model_calibration_score = EXCLUDED.model_calibration_score,
            summary_text = EXCLUDED.summary_text,
            next_month_plan = EXCLUDED.next_month_plan
        RETURNING id
    """
    params = {
        "month": review["month"],
        "total_stake": review.get("total_stake", 0),
        "total_prize": review.get("total_prize", 0),
        "profit_loss": review.get("profit_loss", 0),
        "roi": review.get("roi", 0),
        "max_drawdown": review.get("max_drawdown", 0),
        "longest_losing_streak": review.get("longest_losing_streak", 0),
        "best_strategy_pool": review.get("best_strategy_pool"),
        "worst_strategy_pool": review.get("worst_strategy_pool"),
        "model_calibration_score": review.get("model_calibration_score", 0),
        "summary_text": review.get("summary_text", ""),
        "next_month_plan": review.get("next_month_plan", ""),
    }
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def list_monthly_reviews(conn: Any, limit: int = 12) -> list[dict]:
    """List monthly reviews, newest first."""
    sql = "SELECT * FROM monthly_reviews ORDER BY month DESC LIMIT %(limit)s"
    with conn.cursor() as cur:
        cur.execute(sql, {"limit": limit})
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "month": r[1],
            "total_stake": float(r[2]) if r[2] else 0,
            "total_prize": float(r[3]) if r[3] else 0,
            "profit_loss": float(r[4]) if r[4] else 0,
            "roi": float(r[5]) if r[5] else 0,
            "max_drawdown": float(r[6]) if r[6] else 0,
            "longest_losing_streak": r[7],
            "best_strategy_pool": r[8],
            "worst_strategy_pool": r[9],
            "model_calibration_score": float(r[10]) if r[10] else 0,
            "summary_text": r[11],
            "next_month_plan": r[12],
            "created_at": r[13].isoformat()
            if hasattr(r[13], "isoformat")
            else str(r[13])
            if r[13]
            else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Prediction error analysis
# ---------------------------------------------------------------------------


def create_error_analyses_batch(conn: Any, errors: list[dict]) -> int:
    """Batch-insert prediction error analyses. Returns count inserted."""
    sql = """
        INSERT INTO prediction_error_analysis (
            prediction_id, match_id, error_type, error_level,
            root_cause, model_probability, market_probability,
            actual_result, suggested_fix, created_at
        ) VALUES (
            %(prediction_id)s, %(match_id)s, %(error_type)s, %(error_level)s,
            %(root_cause)s, %(model_probability)s, %(market_probability)s,
            %(actual_result)s, %(suggested_fix)s, now()
        )
        RETURNING id
    """
    count = 0
    with conn.cursor() as cur:
        for err in errors:
            try:
                cur.execute(
                    sql,
                    {
                        "prediction_id": err.get("prediction_id"),
                        "match_id": err.get("match_id"),
                        "error_type": err.get("error_type"),
                        "error_level": err.get("error_level", "low"),
                        "root_cause": err.get("root_cause", ""),
                        "model_probability": err.get("model_probability", 0),
                        "market_probability": err.get("market_probability", 0),
                        "actual_result": err.get("actual_result"),
                        "suggested_fix": err.get("suggested_fix", ""),
                    },
                )
                if cur.fetchone():
                    count += 1
            except Exception:
                pass
    conn.commit()
    return count


def list_error_analyses(
    conn: Any, match_id: int | None = None, error_type: str | None = None, limit: int = 50
) -> list[dict]:
    """List error analyses, optionally filtered."""
    conditions = []
    params: dict[str, Any] = {"limit": limit}

    if match_id:
        conditions.append("pea.match_id = %(match_id)s")
        params["match_id"] = match_id
    if error_type:
        conditions.append("pea.error_type = %(error_type)s")
        params["error_type"] = error_type

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"""
        SELECT pea.id, pea.prediction_id, pea.match_id,
               pea.error_type, pea.error_level, pea.root_cause,
               pea.model_probability, pea.market_probability,
               pea.actual_result, pea.suggested_fix, pea.created_at,
               m.home_team_name, m.away_team_name
        FROM prediction_error_analysis pea
        JOIN official_matches m ON m.id = pea.match_id
        WHERE {where_clause}
        ORDER BY pea.created_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "prediction_id": r[1],
            "match_id": r[2],
            "error_type": r[3],
            "error_level": r[4],
            "root_cause": r[5],
            "model_probability": float(r[6]) if r[6] else 0,
            "market_probability": float(r[7]) if r[7] else 0,
            "actual_result": r[8],
            "suggested_fix": r[9],
            "created_at": r[10].isoformat()
            if hasattr(r[10], "isoformat")
            else str(r[10])
            if r[10]
            else None,
            "home_team_name": r[11],
            "away_team_name": r[12],
        }
        for r in rows
    ]


def get_error_summary(conn: Any, days: int = 7) -> dict:
    """Get error type distribution for recent days."""
    sql = """
        SELECT error_type, error_level, COUNT(*) AS count
        FROM prediction_error_analysis
        WHERE created_at >= now() - (%(days)s * INTERVAL '1 day')
        GROUP BY error_type, error_level
        ORDER BY count DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"days": days})
        rows = cur.fetchall()

    error_types: dict[str, dict] = {}
    total = 0
    for r in rows:
        etype, level, count = r[0], r[1], r[2]
        if etype not in error_types:
            error_types[etype] = {"total": 0, "by_level": {}}
        error_types[etype]["total"] += count
        error_types[etype]["by_level"][level] = count
        total += count

    return {"total_errors": total, "days": days, "error_types": error_types}


# ---------------------------------------------------------------------------
# Bankroll transaction integration
# ---------------------------------------------------------------------------


def create_bankroll_transaction(conn: Any, txn: dict) -> int | None:
    """Insert a bankroll transaction and update account balance atomically."""
    sql_select = """
        SELECT id, current_balance FROM bankroll_accounts
        WHERE account_type = %(account_type)s LIMIT 1
    """
    sql_insert = """
        INSERT INTO bankroll_transactions (
            account_id, transaction_type, amount,
            related_ticket_id, balance_after, remark, created_at
        ) VALUES (
            %(account_id)s, %(transaction_type)s, %(amount)s,
            %(related_ticket_id)s, %(balance_after)s, %(remark)s, now()
        )
        RETURNING id
    """
    sql_update = """
        UPDATE bankroll_accounts SET current_balance = %(balance)s, updated_at = now()
        WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql_select, {"account_type": txn.get("account_type", "simulation")})
        account = cur.fetchone()
        if not account:
            return None

        account_id = account[0]
        current = float(account[1] or 0)
        amount = float(txn.get("amount", 0))
        balance_after = current + amount

        cur.execute(
            sql_insert,
            {
                "account_id": account_id,
                "transaction_type": txn.get("transaction_type", "settlement"),
                "amount": amount,
                "related_ticket_id": txn.get("related_ticket_id"),
                "balance_after": balance_after,
                "remark": txn.get("remark", ""),
            },
        )
        row = cur.fetchone()
        if row:
            cur.execute(sql_update, {"balance": balance_after, "id": account_id})
    conn.commit()
    return row[0] if row else None


def get_play_type_win_rate(conn: Any, days: int = 30) -> list[dict[str, Any]]:
    """Return daily win-rate per play_type from settled tickets.

    Each row: {settle_date, play_type, total, wins, win_rate}
    Ordered by settle_date ASC, play_type.
    """
    sql = """
        SELECT
            (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date::text AS settle_date,
            rti.play_type,
            COUNT(*) AS total,
            SUM(CASE WHEN ts.is_won THEN 1 ELSE 0 END) AS wins,
            ROUND(
                SUM(CASE WHEN ts.is_won THEN 1 ELSE 0 END)::numeric
                / NULLIF(COUNT(*), 0)::numeric, 4
            ) AS win_rate
        FROM ticket_settlements ts
        JOIN real_ticket_items rti
            ON ts.ticket_id = rti.real_ticket_id
            AND ts.ticket_source = 'real'
        WHERE ts.is_won IS NOT NULL
          AND (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date
              >= timezone('Asia/Shanghai', NOW())::date - %(days)s::int
        GROUP BY (ts.settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date,
                 rti.play_type
        ORDER BY settle_date ASC, play_type
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"days": days})
        rows = cur.fetchall()

    return [
        {
            "settle_date": r[0],
            "play_type": r[1],
            "total": r[2],
            "wins": r[3],
            "win_rate": float(r[4]) if r[4] is not None else 0.0,
        }
        for r in rows
    ]
