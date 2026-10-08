"""Idempotent repairs for settlements created by legacy result-code logic."""

from __future__ import annotations

import json
from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from scripts.result_codes import normalize_result
from scripts.simulator_calculator import calculate_winning_prize


def _calculate_tax(prize: float) -> float:
    return (prize - 10_000) * 0.20 if prize > 10_000 else 0.0


def correct_legacy_settlement_detail(detail: dict[str, Any], stake: float) -> dict[str, Any] | None:
    """Normalize H/D/A selections and return corrected settlement values."""
    corrected = deepcopy(detail)
    changed = False
    items = corrected.get("items")
    if not isinstance(items, list):
        return None

    for item in items:
        if not isinstance(item, dict):
            continue
        play_type = str(item.get("play_type") or "")
        original = str(item.get("option_code") or "")
        normalized = normalize_result(play_type, original) or original
        if normalized == original:
            continue
        item["option_code"] = normalized
        item["original_option_code"] = original
        actual = normalize_result(play_type, item.get("actual_result"))
        item["is_won"] = bool(item.get("is_void")) or normalized == actual
        changed = True

    if not changed:
        return None

    pass_type = corrected.get("pass_type") or "single"
    multiple = int(corrected.get("multiple") or 1)
    prize = calculate_winning_prize(items, pass_type, multiple)
    tax = _calculate_tax(prize)
    net_prize = prize - tax
    profit_loss = net_prize - stake
    corrected["all_won"] = all(bool(item.get("is_won")) for item in items)
    corrected["has_winning_combination"] = prize > 0
    return {
        "detail": corrected,
        "is_won": prize > 0,
        "prize_amount": round(prize, 2),
        "tax_amount": round(tax, 2),
        "net_prize": round(net_prize, 2),
        "profit_loss": round(profit_loss, 2),
        "roi": round(profit_loss / stake, 6) if stake > 0 else 0.0,
    }


def _adjust_real_account(conn: Any, ticket_id: int, delta: float) -> None:
    """Apply a correction only when an optional real-money account exists."""
    if abs(delta) < 0.005:
        return
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, current_balance FROM bankroll_accounts "
            "WHERE account_type = 'real' ORDER BY id LIMIT 1 FOR UPDATE"
        )
        account = cur.fetchone()
        if not account:
            return
        balance_after = Decimal(str(account[1] or 0)) + Decimal(str(delta)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        cur.execute(
            """
            INSERT INTO bankroll_transactions (
                account_id, transaction_type, amount, related_ticket_id,
                balance_after, remark, created_at
            ) VALUES (%s, 'settlement_adjustment', %s, %s, %s, %s, now())
            """,
            (account[0], delta, ticket_id, balance_after, f"实票 #{ticket_id} 历史结算编码修正"),
        )
        cur.execute(
            "UPDATE bankroll_accounts SET current_balance = %s, updated_at = now() WHERE id = %s",
            (balance_after, account[0]),
        )


def reopen_orphaned_settled_real_tickets(conn: Any) -> int:
    """Return settled real tickets without a ledger row to the automatic queue."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE real_tickets ticket
            SET settlement_status = 'pending', updated_at = now()
            WHERE ticket.settlement_status = 'settled'
              AND NOT EXISTS (
                  SELECT 1
                  FROM ticket_settlements settlement
                  WHERE settlement.ticket_source = 'real'
                    AND settlement.ticket_id = ticket.id
              )
            """
        )
        reopened = int(cur.rowcount or 0)
    conn.commit()
    return reopened


def repair_legacy_real_settlements(conn: Any) -> dict[str, Any]:
    """Repair legacy real-ticket settlements once; repeated calls are no-ops."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, ticket_id, stake_amount, net_prize, settlement_detail_json
            FROM ticket_settlements
            WHERE ticket_source = 'real'
              AND EXISTS (
                  SELECT 1 FROM jsonb_array_elements(
                      CASE WHEN jsonb_typeof(settlement_detail_json->'items') = 'array'
                           THEN settlement_detail_json->'items' ELSE '[]'::jsonb END
                  ) item
                  WHERE (item->>'play_type' IN ('spf', 'rqspf', 'bqc')
                         AND item->>'option_code' ~ '[HhDdAa]')
                     OR (item->>'play_type' = 'bf' AND item->>'option_code' <>
                         REPLACE(REPLACE(item->>'option_code', '-', ':'), ' ', ''))
                     OR (item->>'play_type' = 'zjq' AND item->>'option_code' IN ('7+', '7plus', '7以上'))
                     OR item->>'option_code' <> BTRIM(item->>'option_code')
              )
            ORDER BY id
            FOR UPDATE
            """
        )
        rows = cur.fetchall()

    repaired = 0
    financial_adjusted = 0
    net_delta = 0.0
    for settlement_id, ticket_id, stake, old_net_prize, detail in rows:
        correction = correct_legacy_settlement_detail(detail or {}, float(stake or 0))
        if correction is None:
            continue
        delta = float(correction["net_prize"]) - float(old_net_prize or 0)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ticket_settlements
                SET is_won = %s, prize_amount = %s, tax_amount = %s,
                    net_prize = %s, profit_loss = %s, roi = %s,
                    settlement_detail_json = %s
                WHERE id = %s
                """,
                (
                    correction["is_won"],
                    correction["prize_amount"],
                    correction["tax_amount"],
                    correction["net_prize"],
                    correction["profit_loss"],
                    correction["roi"],
                    json.dumps(correction["detail"], ensure_ascii=False),
                    settlement_id,
                ),
            )
        _adjust_real_account(conn, int(ticket_id), delta)
        repaired += 1
        if abs(delta) >= 0.005:
            financial_adjusted += 1
            net_delta += delta

    conn.commit()
    return {
        "repaired": repaired,
        "financial_adjusted": financial_adjusted,
        "net_delta": round(net_delta, 2),
    }
