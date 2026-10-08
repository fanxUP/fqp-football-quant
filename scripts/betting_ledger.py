"""Filter the complete ticket ledger before paging and loading ticket details."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any

_LEDGER_SQL = """
    WITH tickets AS (
        SELECT 'simulator'::text AS source, id, 'me'::text AS owner,
               created_at, created_at::date AS purchase_date,
               COALESCE(total_cost, 0) AS stake, status AS original_status
        FROM simulator_tickets
        UNION ALL
        SELECT 'real', id,
               CASE WHEN source_type IN ('agent', 'agent_real') THEN 'agent' ELSE 'me' END,
               created_at, COALESCE(purchase_time, created_at)::date,
               COALESCE(total_amount, 0), settlement_status
        FROM real_tickets
        UNION ALL
        SELECT 'simulation', st.id, 'agent', st.created_at, st.created_at::date,
               COALESCE(st.suggested_stake, 0), st.ticket_status
        FROM simulation_tickets st
        WHERE st.ticket_status IN ('generated', 'activated', 'settled')
          AND EXISTS (SELECT 1 FROM simulation_ticket_items i WHERE i.ticket_id = st.id)
    ), ledger AS (
        SELECT t.*, COALESCE(t.created_at, TIMESTAMP '1970-01-01') AS sort_time,
               CASE WHEN s.id IS NOT NULL THEN 'settled'
                    WHEN original_status IN ('settled', 'won', 'lost') THEN original_status
                    WHEN original_status IN ('pending', 'generated', 'activated') THEN 'pending'
                    ELSE 'cancelled' END AS status,
               s.is_won, COALESCE(s.profit_loss, 0) AS profit_loss
        FROM tickets t
        LEFT JOIN LATERAL (
            SELECT id, is_won, profit_loss FROM ticket_settlements
            WHERE ticket_source = t.source AND ticket_id = t.id
            ORDER BY id DESC LIMIT 1
        ) s ON TRUE
    ), filtered AS (
        SELECT * FROM ledger
        WHERE (%(owner)s IS NULL OR owner = %(owner)s)
          AND (%(date)s IS NULL OR purchase_date = %(date)s::date)
          AND (%(status)s IS NULL OR status = %(status)s
               OR (%(status)s = 'won' AND status = 'settled' AND is_won = TRUE)
               OR (%(status)s = 'lost' AND status = 'settled' AND is_won = FALSE))
    )
"""


def _encode_cursor(row: tuple) -> str:
    return base64.urlsafe_b64encode(
        json.dumps([row[2].isoformat(), row[1], row[0]]).encode()
    ).decode()


def read_ledger_page(
    conn: Any,
    *,
    owner: str | None,
    date: str | None,
    status: str | None,
    limit: int,
    cursor: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "owner": owner,
        "date": date,
        "status": status,
        "limit": limit + 1,
        "cursor_time": None,
        "cursor_id": None,
        "cursor_source": None,
    }
    if cursor:
        try:
            timestamp, ticket_id, source = json.loads(base64.urlsafe_b64decode(cursor))
            parsed_time = datetime.fromisoformat(timestamp)
            if parsed_time.tzinfo is not None or not isinstance(ticket_id, int) or ticket_id < 1:
                raise ValueError("Invalid cursor fields")
            if source not in {"real", "simulator", "simulation"}:
                raise ValueError("Invalid cursor source")
            params.update(cursor_time=parsed_time, cursor_id=ticket_id, cursor_source=source)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid ticket page cursor") from exc

    with conn.cursor() as cur:
        cur.execute(
            _LEDGER_SQL
            + """
            SELECT owner, COUNT(*), COALESCE(SUM(stake), 0),
                   COUNT(*) FILTER (WHERE status IN ('settled', 'won', 'lost')),
                   COUNT(*) FILTER (WHERE status = 'pending'),
                   COALESCE(SUM(profit_loss), 0)
            FROM filtered GROUP BY owner
            """,
            params,
        )
        by_owner = {
            row[0]: {
                "total": int(row[1]),
                "stake": float(row[2]),
                "settled": int(row[3]),
                "pending": int(row[4]),
                "profitLoss": float(row[5]),
            }
            for row in cur.fetchall()
        }
        summary = {
            key: sum(value[key] for value in by_owner.values())
            for key in ("total", "stake", "settled", "pending", "profitLoss")
        }
        cur.execute(
            _LEDGER_SQL
            + """
            SELECT source, id, sort_time FROM filtered
            WHERE %(cursor_time)s IS NULL
               OR (sort_time, id, source) <
                  (%(cursor_time)s::timestamp, %(cursor_id)s::bigint, %(cursor_source)s::text)
            ORDER BY sort_time DESC, id DESC, source DESC LIMIT %(limit)s
            """,
            params,
        )
        rows = cur.fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        records: dict[tuple[str, int], dict] = {}
        for source, table, item_table, item_fk in (
            ("simulator", "simulator_tickets", "simulator_ticket_items", "ticket_id"),
            ("real", "real_tickets", "real_ticket_items", "real_ticket_id"),
            ("simulation", "simulation_tickets", "simulation_ticket_items", "ticket_id"),
        ):
            ids = [row[1] for row in page if row[0] == source]
            if not ids:
                continue
            cur.execute(
                f"SELECT t.id, to_jsonb(t), "
                f"(SELECT COUNT(*) FROM {item_table} i WHERE i.{item_fk} = t.id) "
                f"FROM {table} t WHERE t.id = ANY(%s)",
                (ids,),
            )
            for ticket_id, raw, item_count in cur.fetchall():
                records[(source, ticket_id)] = {**raw, "item_count": item_count}
        cur.execute(
            """
            SELECT ticket_source, ticket_id, settle_time, is_won, stake_amount,
                   prize_amount, tax_amount, net_prize, profit_loss, roi
            FROM ticket_settlements
            WHERE (ticket_source = 'real' AND ticket_id = ANY(%s))
               OR (ticket_source = 'simulation' AND ticket_id = ANY(%s))
               OR (ticket_source = 'simulator' AND ticket_id = ANY(%s))
            ORDER BY id
            """,
            tuple(
                [row[1] for row in page if row[0] == source]
                for source in ("real", "simulation", "simulator")
            ),
        )
        settlements = list(cur.fetchall())
    return {
        "records": [
            (row[0], records[(row[0], row[1])]) for row in page if (row[0], row[1]) in records
        ],
        "settlements": settlements,
        "summary": summary,
        "byOwner": by_owner,
        "nextCursor": _encode_cursor(page[-1]) if has_more and page else None,
    }
