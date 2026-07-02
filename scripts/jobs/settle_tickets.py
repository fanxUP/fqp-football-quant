"""Ticket settlement job.

Finds matches with confirmed results, calculates P&L for simulation and real
tickets, and writes settlements with bankroll updates.

Stage 5: idempotent — safe to run multiple times per hour.
No-data path returns {"status": "ok", "settled": 0} when no results exist.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.real_ticket_storage import (
    create_bankroll_transaction,
    create_settlement,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _calculate_tax(prize: float) -> float:
    """Chinese lottery tax: 20% on prizes over 10,000 CNY."""
    if prize > 10000:
        return (prize - 10000) * 0.20
    return 0.0


def run(dry_run: bool = False) -> dict[str, Any]:
    """Settle all unsettled tickets that have confirmed match results."""
    if dry_run:
        return {"status": "dry_run", "message": "settle tickets (dry run)"}

    with get_db() as conn:
        # 1. Find confirmed results
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.match_id, r.spf_result, r.full_home_goals, r.full_away_goals,
                       r.result_status, m.home_team_name, m.away_team_name
                FROM official_results r
                JOIN official_matches m ON m.id = r.match_id
                WHERE r.result_status = 'confirmed'
                  AND r.spf_result IS NOT NULL
                ORDER BY r.match_id
                """
            )
            results = cur.fetchall()

        if not results:
            return {"status": "ok", "settled": 0, "note": "no confirmed results"}

        # Build result lookup: match_id -> spf_result
        result_map: dict[int, str] = {}
        match_info: dict[int, dict] = {}
        for r in results:
            result_map[r[0]] = r[1]  # match_id -> spf_result
            match_info[r[0]] = {
                "full_home_goals": r[2],
                "full_away_goals": r[3],
                "home_team": r[5],
                "away_team": r[6],
            }

        total_settled = 0
        sim_settled = 0
        real_settled = 0
        total_prize = 0.0

        # 2. Settle simulation tickets
        for match_id, _spf_result in result_map.items():
            with conn.cursor() as cur:
                # Find unsettled simulation ticket items for this match
                cur.execute(
                    """
                    SELECT sti.id AS item_id, sti.ticket_id, sti.option_code,
                           sti.sp_value, sti.play_type,
                           st.suggested_stake, st.pass_type, st.multiple,
                           st.ticket_status
                    FROM simulation_ticket_items sti
                    JOIN simulation_tickets st ON st.id = sti.ticket_id
                    WHERE sti.match_id = %s
                      AND st.ticket_status IN ('generated', 'activated')
                    ORDER BY sti.ticket_id
                    """,
                    (match_id,),
                )
                items = cur.fetchall()

            if not items:
                continue

            # Group items by ticket_id
            tickets: dict[int, dict] = {}
            for item in items:
                tid = item[1]
                if tid not in tickets:
                    tickets[tid] = {
                        "ticket_id": tid,
                        "suggested_stake": float(item[5] or 0),
                        "pass_type": item[6],
                        "multiple": item[7] or 1,
                        "status": item[8],
                        "items": [],
                    }
                tickets[tid]["items"].append(
                    {
                        "item_id": item[0],
                        "option_code": item[2],
                        "sp_value": float(item[3] or 0),
                        "play_type": item[4],
                    }
                )

            # Settle each ticket
            for tid, ticket in tickets.items():
                # Check idempotency
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM ticket_settlements WHERE ticket_source = 'simulation' AND ticket_id = %s",
                        (tid,),
                    )
                    if cur.fetchone():
                        continue  # already settled

                # Determine win/loss
                stake = ticket["suggested_stake"] * ticket["multiple"]
                all(
                    item["option_code"] == result_map[match_id]
                    for item in ticket["items"]
                    if match_id in result_map
                )

                # For multi-match passes, we need all matches to have results
                # This simplified version checks the current match only.
                # Full pass settlement needs all match_ids for the ticket.
                # We use a simpler approach: check all items against known results.
                # Items whose match hasn't been settled yet cause the ticket to be skipped.

                # Get all match_ids for this ticket
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT match_id, option_code, sp_value FROM simulation_ticket_items WHERE ticket_id = %s",
                        (tid,),
                    )
                    all_items = cur.fetchall()

                unsettled_match = False
                ticket_all_won = True
                product_sp = 1.0
                detail_items = []

                for ai in all_items:
                    ai_match_id = ai[0]
                    ai_option = ai[1]
                    ai_sp = float(ai[2] or 0)

                    if ai_match_id not in result_map:
                        unsettled_match = True
                        break  # skip this ticket — not all matches settled

                    item_won = ai_option == result_map[ai_match_id]
                    if not item_won:
                        ticket_all_won = False

                    product_sp *= ai_sp
                    detail_items.append(
                        {
                            "match_id": ai_match_id,
                            "option_code": ai_option,
                            "sp_value": ai_sp,
                            "actual_result": result_map[ai_match_id],
                            "is_won": item_won,
                        }
                    )

                if unsettled_match:
                    continue  # skip — wait for all match results

                # Calculate prize
                if ticket_all_won:
                    if ticket["pass_type"] == "single":
                        prize = stake * detail_items[0]["sp_value"] if detail_items else 0
                    else:
                        # Pass-type: stake × product(all sp_values)
                        prize = stake * product_sp
                else:
                    prize = 0.0

                tax = _calculate_tax(prize)
                net_prize = prize - tax
                profit_loss = net_prize - stake
                roi = profit_loss / stake if stake > 0 else 0.0

                # Insert settlement
                settlement_id = create_settlement(
                    conn,
                    {
                        "ticket_source": "simulation",
                        "ticket_id": tid,
                        "settle_time": _now(),
                        "is_won": ticket_all_won,
                        "stake_amount": stake,
                        "prize_amount": prize,
                        "tax_amount": tax,
                        "net_prize": net_prize,
                        "profit_loss": profit_loss,
                        "roi": roi,
                        "settlement_detail_json": {
                            "source": "simulation",
                            "items": detail_items,
                            "pass_type": ticket["pass_type"],
                            "multiple": ticket["multiple"],
                            "all_won": ticket_all_won,
                        },
                    },
                )

                if settlement_id:
                    # Bankroll: debit the stake (spend)
                    create_bankroll_transaction(
                        conn,
                        {
                            "account_type": "simulation",
                            "transaction_type": "stake_settled",
                            "amount": -stake,
                            "related_ticket_id": tid,
                            "remark": f"Settlement: ticket {tid} stake {stake:.2f}",
                        },
                    )

                    # Bankroll: credit the prize (if won)
                    if ticket_all_won and net_prize > 0:
                        create_bankroll_transaction(
                            conn,
                            {
                                "account_type": "simulation",
                                "transaction_type": "prize_credit",
                                "amount": net_prize,
                                "related_ticket_id": tid,
                                "remark": f"Settlement: ticket {tid} prize {prize:.2f}, net {net_prize:.2f}",
                            },
                        )

                    # Update ticket status
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE simulation_tickets SET ticket_status = 'settled' WHERE id = %s",
                            (tid,),
                        )
                    conn.commit()

                    total_settled += 1
                    sim_settled += 1
                    total_prize += prize

        # 3. Settle real tickets
        for match_id, _spf_result in result_map.items():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT rti.real_ticket_id, rti.option_code, rti.sp_value,
                           rti.play_type, rti.match_id,
                           rt.total_amount, rt.pass_type, rt.multiple,
                           rt.confirm_status, rt.settlement_status
                    FROM real_ticket_items rti
                    JOIN real_tickets rt ON rt.id = rti.real_ticket_id
                    WHERE rti.match_id = %s
                      AND rt.confirm_status = 'confirmed'
                      AND rt.settlement_status = 'pending'
                    ORDER BY rti.real_ticket_id
                    """,
                    (match_id,),
                )
                ritems = cur.fetchall()

            if not ritems:
                continue

            # Group by real_ticket_id
            rtickets: dict[int, dict] = {}
            for ri in ritems:
                rtid = ri[0]
                if rtid not in rtickets:
                    rtickets[rtid] = {
                        "ticket_id": rtid,
                        "total_amount": float(ri[5] or 0),
                        "pass_type": ri[6],
                        "multiple": ri[7] or 1,
                        "items": [],
                    }
                rtickets[rtid]["items"].append(
                    {
                        "option_code": ri[1],
                        "sp_value": float(ri[2] or 0),
                        "play_type": ri[3],
                        "match_id": ri[4],
                    }
                )

            for rtid, rticket in rtickets.items():
                # Check idempotency
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM ticket_settlements WHERE ticket_source = 'real' AND ticket_id = %s",
                        (rtid,),
                    )
                    if cur.fetchone():
                        continue

                # Get all items for this real ticket
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT match_id, option_code, sp_value FROM real_ticket_items WHERE real_ticket_id = %s",
                        (rtid,),
                    )
                    all_ritems = cur.fetchall()

                unsettled_match = False
                real_all_won = True
                real_product_sp = 1.0
                real_detail = []

                for ai in all_ritems:
                    ai_match_id = ai[0]
                    ai_option = ai[1]
                    ai_sp = float(ai[2] or 0)

                    if ai_match_id not in result_map:
                        unsettled_match = True
                        break

                    item_won = ai_option == result_map[ai_match_id]
                    if not item_won:
                        real_all_won = False

                    real_product_sp *= ai_sp
                    real_detail.append(
                        {
                            "match_id": ai_match_id,
                            "option_code": ai_option,
                            "sp_value": ai_sp,
                            "actual_result": result_map[ai_match_id],
                            "is_won": item_won,
                        }
                    )

                if unsettled_match:
                    continue

                stake = rticket["total_amount"]
                if real_all_won:
                    prize = stake * real_product_sp
                else:
                    prize = 0.0

                tax = _calculate_tax(prize)
                net_prize = prize - tax
                profit_loss = net_prize - stake
                roi = profit_loss / stake if stake > 0 else 0.0

                settlement_id = create_settlement(
                    conn,
                    {
                        "ticket_source": "real",
                        "ticket_id": rtid,
                        "settle_time": _now(),
                        "is_won": real_all_won,
                        "stake_amount": stake,
                        "prize_amount": prize,
                        "tax_amount": tax,
                        "net_prize": net_prize,
                        "profit_loss": profit_loss,
                        "roi": roi,
                        "settlement_detail_json": {
                            "source": "real",
                            "items": real_detail,
                            "pass_type": rticket["pass_type"],
                            "multiple": rticket["multiple"],
                            "all_won": real_all_won,
                        },
                    },
                )

                if settlement_id:
                    # Update real ticket settlement status
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE real_tickets SET settlement_status = 'settled', updated_at = now() WHERE id = %s",
                            (rtid,),
                        )
                    conn.commit()

                    total_settled += 1
                    real_settled += 1
                    total_prize += prize

        return {
            "status": "ok",
            "settled": total_settled,
            "simulation_settled": sim_settled,
            "real_settled": real_settled,
            "total_prize": round(total_prize, 2),
        }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
