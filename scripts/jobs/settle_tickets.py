"""Ticket settlement job.

Finds matches with confirmed results, calculates P&L for simulation and real
tickets, and writes settlements with bankroll updates.

Stage 5: idempotent — safe to run multiple times per hour.
No-data path returns {"status": "ok", "settled": 0} when no results exist.
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import utc_now_iso
from scripts.jobs.settlement_repairs import repair_legacy_real_settlements
from scripts.play_type_registry import result_column
from scripts.real_ticket_storage import (
    create_bankroll_transaction,
    create_settlement,
)
from scripts.result_codes import normalize_result as _normalize_result
from scripts.result_status import is_void_official_result as _is_void_result
from scripts.simulator_calculator import calculate_winning_prize
from scripts.simulator_storage import update_ticket_status as update_sim_ticket_status


def _calculate_tax(prize: float) -> float:
    """Chinese lottery tax: 20% on prizes over 10,000 CNY."""
    if prize > 10000:
        return (prize - 10000) * 0.20
    return 0.0


def _derive_rqspf_result(
    handicap: Any, full_home_goals: Any, full_away_goals: Any
) -> str | None:
    """Derive the ticket-specific handicap result from its locked handicap."""
    if handicap is None or full_home_goals is None or full_away_goals is None:
        return None
    adjusted_home = float(full_home_goals) + float(handicap)
    away = float(full_away_goals)
    if adjusted_home > away:
        return "3"
    if adjusted_home == away:
        return "1"
    return "0"


def _resolve_ticket_items(
    items: list[dict[str, Any]], full_result_map: dict[int, dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """Resolve every selection against its own play result.

    A ticket must remain pending until every selected play has a confirmed
    result. Selections from the same match are alternatives and are preserved
    individually for the combination calculator.
    """
    detail: list[dict[str, Any]] = []
    for item in items:
        match_id = int(item["match_id"])
        play_type = str(item["play_type"])
        result = full_result_map.get(match_id)
        if result is None:
            return None

        is_void = bool(result.get("is_void"))
        column = result_column(play_type)
        if not is_void and not column:
            return None

        actual_result = None
        if not is_void and play_type == "rqspf":
            actual_result = _derive_rqspf_result(
                item.get("handicap"),
                result.get("full_home_goals"),
                result.get("full_away_goals"),
            )
        if not is_void and actual_result is None:
            actual_result = _normalize_result(play_type, result.get(column))
        if not is_void and actual_result is None:
            return None

        original_option_code = str(item["option_code"])
        option_code = _normalize_result(play_type, original_option_code) or original_option_code
        original_sp_value = float(item.get("sp_value") or 0)
        detail.append(
            {
                "match_id": match_id,
                "play_type": play_type,
                "option_code": option_code,
                "sp_value": 1.0 if is_void else original_sp_value,
                "handicap": (
                    float(item["handicap"]) if item.get("handicap") is not None else None
                ),
                "is_dan": bool(item.get("is_dan", False)),
                "actual_result": "void" if is_void else actual_result,
                "is_won": True if is_void else option_code == actual_result,
                "is_void": is_void,
                **(
                    {"original_option_code": original_option_code}
                    if option_code != original_option_code
                    else {}
                ),
                **({"original_sp_value": original_sp_value} if is_void else {}),
            }
        )
    return detail


def _calculate_agent_prize(
    detail: list[dict[str, Any]],
    pass_type: str,
    multiple: int,
    bet_count: int,
    stake: float,
) -> float:
    """Scale the nominal 2-yuan combination payout to the committed stake."""
    nominal_cost = float(bet_count) * 2.0 * float(multiple)
    if nominal_cost <= 0 or stake <= 0:
        return 0.0
    nominal_prize = calculate_winning_prize(detail, pass_type, multiple)
    return round(nominal_prize * stake / nominal_cost, 2)


def run(dry_run: bool = False) -> dict[str, Any]:
    """Settle all unsettled tickets that have confirmed match results."""
    if dry_run:
        return {"status": "dry_run", "message": "settle tickets (dry run)"}

    with get_db() as conn:
        legacy_repairs = repair_legacy_real_settlements(conn)
        # 1. Find confirmed results
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.match_id, r.spf_result, r.rqspf_result,
                       r.total_goals_result, r.score_result, r.half_full_result,
                       r.full_home_goals, r.full_away_goals,
                       r.result_status, r.raw_json,
                       m.home_team_name, m.away_team_name
                FROM official_results r
                JOIN official_matches m ON m.id = r.match_id
                WHERE r.result_status IN ('confirmed', 'void', 'refund', 'refunded')
                ORDER BY r.match_id
                """
            )
            results = cur.fetchall()

        if not results:
            return {
                "status": "ok",
                "settled": 0,
                "note": "no confirmed results",
                "legacy_repairs": legacy_repairs,
            }

        # Build result lookup: match_id -> full results
        result_map: dict[int, str | None] = {}
        full_result_map: dict[int, dict] = {}
        match_info: dict[int, dict] = {}
        for r in results:
            is_void = _is_void_result(r[9], r[8])
            if not is_void and not any(value is not None for value in r[1:8]):
                continue
            result_map[r[0]] = r[1]  # match_id -> spf_result
            full_result_map[r[0]] = {
                "spf_result": r[1],
                "rqspf_result": r[2],
                "total_goals_result": r[3],
                "score_result": r[4],
                "half_full_result": r[5],
                "full_home_goals": r[6],
                "full_away_goals": r[7],
                "is_void": is_void,
            }
            match_info[r[0]] = {
                "full_home_goals": r[6],
                "full_away_goals": r[7],
                "home_team": r[10],
                "away_team": r[11],
            }

        if not result_map:
            return {
                "status": "ok",
                "settled": 0,
                "note": "no actionable results",
                "legacy_repairs": legacy_repairs,
            }

        total_settled = 0
        sim_settled = 0
        simulator_settled = 0
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
                           st.ticket_status, st.bet_count
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
                        "bet_count": item[9] or 1,
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
                # suggested_stake is the ticket's already-calculated total
                # cost (注数 × 2 元 × 倍数), so do not multiply it again.
                stake = ticket["suggested_stake"]

                # For multi-match passes, we need all matches to have results
                # This simplified version checks the current match only.
                # Full pass settlement needs all match_ids for the ticket.
                # We use a simpler approach: check all items against known results.
                # Items whose match hasn't been settled yet cause the ticket to be skipped.

                # Get all match_ids for this ticket
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT sti.match_id, sti.option_code, sti.sp_value,
                                  sti.play_type, odds.handicap
                           FROM simulation_ticket_items sti
                           LEFT JOIN official_odds_snapshots odds
                             ON odds.id = sti.odds_snapshot_id
                           WHERE sti.ticket_id = %s""",
                        (tid,),
                    )
                    all_items = cur.fetchall()

                detail_items = _resolve_ticket_items(
                    [
                        {
                            "match_id": item[0],
                            "option_code": item[1],
                            "sp_value": item[2],
                            "play_type": item[3],
                            "handicap": item[4],
                        }
                        for item in all_items
                    ],
                    full_result_map,
                )
                if detail_items is None:
                    continue  # skip — wait for all match results

                pass_type = ticket["pass_type"]
                multiple = ticket["multiple"]
                prize = _calculate_agent_prize(
                    detail_items,
                    pass_type,
                    multiple,
                    ticket["bet_count"],
                    stake,
                )
                agent_ticket_won = prize > 0

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
                        "settle_time": utc_now_iso(),
                        "is_won": agent_ticket_won,
                        "stake_amount": stake,
                        "prize_amount": prize,
                        "tax_amount": tax,
                        "net_prize": net_prize,
                        "profit_loss": profit_loss,
                        "roi": roi,
                        "settlement_detail_json": {
                            "source": "simulation",
                            "items": detail_items,
                            "pass_type": pass_type,
                            "multiple": multiple,
                            "all_won": all(item["is_won"] for item in detail_items),
                            "has_winning_combination": agent_ticket_won,
                        },
                    },
                )

                if settlement_id:
                    # Bankroll: credit the prize (if won)
                    # Note: simulation_tickets had no stake deducted at creation
                    # (they are recommendations). Only record actual prize movement.
                    if agent_ticket_won and net_prize > 0:
                        create_bankroll_transaction(
                            conn,
                            {
                                "account_type": "simulation",
                                "transaction_type": "prize",
                                "amount": net_prize,
                                "related_ticket_id": tid,
                                "remark": f"AI推荐 #{tid} 中奖 {prize:.2f}, 税后 {net_prize:.2f}",
                            },
                        )
                    # Lost: no transaction (AI budget consumed, no real money lost)

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

        # 3. Settle simulator tickets (virtual betting)
        for match_id, _spf_result in result_map.items():
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT sti.id AS item_id, sti.ticket_id, sti.option_code,
                           sti.sp_value, sti.play_type, sti.match_id,
                           st.pass_type, st.multiple, st.total_cost,
                           st.bet_count, st.max_prize, st.status
                    FROM simulator_ticket_items sti
                    JOIN simulator_tickets st ON st.id = sti.ticket_id
                    WHERE sti.match_id = %s
                      AND st.status = 'pending'
                    ORDER BY sti.ticket_id
                    """,
                    (match_id,),
                )
                sitems = cur.fetchall()

            if not sitems:
                continue

            # Group by ticket_id
            simulator_tickets: dict[int, dict] = {}
            for si in sitems:
                tid = si[1]
                if tid not in simulator_tickets:
                    simulator_tickets[tid] = {
                        "ticket_id": tid,
                        "pass_type": si[6],
                        "multiple": si[7] or 1,
                        "total_cost": float(si[8] or 0),
                        "bet_count": si[9],
                        "max_prize": float(si[10] or 0),
                        "items": [],
                    }
                simulator_tickets[tid]["items"].append({
                    "item_id": si[0],
                    "option_code": si[2],
                    "sp_value": float(si[3] or 0),
                    "play_type": si[4],
                    "match_id": si[5],
                })

            for tid, ticket in simulator_tickets.items():
                # Idempotency check
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM ticket_settlements WHERE ticket_source = 'simulator' AND ticket_id = %s",
                        (tid,),
                    )
                    if cur.fetchone():
                        continue

                # Get ALL items for this ticket
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT match_id, option_code, sp_value, play_type, is_dan, handicap
                           FROM simulator_ticket_items WHERE ticket_id = %s""",
                        (tid,),
                    )
                    all_sitems = cur.fetchall()

                detail = _resolve_ticket_items(
                    [
                        {
                            "match_id": item[0],
                            "option_code": item[1],
                            "sp_value": item[2],
                            "play_type": item[3],
                            "is_dan": item[4],
                            "handicap": item[5],
                        }
                        for item in all_sitems
                    ],
                    full_result_map,
                )
                if detail is None:
                    continue

                # Calculate prize
                pass_type = ticket["pass_type"]
                multiple = ticket["multiple"]
                stake = ticket["total_cost"]

                prize = calculate_winning_prize(detail, pass_type, multiple)
                ticket_won = prize > 0

                tax = _calculate_tax(prize)
                net_prize = prize - tax
                profit_loss = net_prize - stake
                roi = profit_loss / stake if stake > 0 else 0.0

                # Insert settlement
                settlement_id = create_settlement(conn, {
                    "ticket_source": "simulator",
                    "ticket_id": tid,
                    "settle_time": utc_now_iso(),
                    "is_won": ticket_won,
                    "stake_amount": stake,
                    "prize_amount": prize,
                    "tax_amount": tax,
                    "net_prize": net_prize,
                    "profit_loss": profit_loss,
                    "roi": roi,
                    "settlement_detail_json": {
                        "source": "simulator",
                        "items": detail,
                        "pass_type": pass_type,
                        "multiple": multiple,
                        "all_won": all(item["is_won"] for item in detail),
                        "has_winning_combination": ticket_won,
                    },
                })

                if settlement_id:
                    # Bankroll: credit the prize (if won) — stake already deducted at purchase
                    if ticket_won and net_prize > 0:
                        create_bankroll_transaction(
                            conn,
                            {
                                "account_type": "simulator",
                                "transaction_type": "prize",
                                "amount": net_prize,
                                "related_ticket_id": tid,
                                "remark": f"Simulator #{tid} 中奖 {prize:.2f}, 税后 {net_prize:.2f}",
                            },
                        )
                    # Lost: no action — stake already deducted at ticket creation

                    # Update ticket status
                    update_sim_ticket_status(conn, tid, "settled")
                    conn.commit()

                    total_settled += 1
                    simulator_settled += 1
                    total_prize += prize

        # 4. Settle real tickets
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
                        """SELECT rti.match_id, rti.option_code, rti.sp_value,
                                  rti.play_type, odds.handicap
                           FROM real_ticket_items rti
                           LEFT JOIN LATERAL (
                               SELECT snapshot.handicap
                               FROM official_odds_snapshots snapshot
                               WHERE snapshot.match_id = rti.match_id
                                 AND snapshot.play_type = rti.play_type
                                 AND snapshot.handicap IS NOT NULL
                                 AND snapshot.snapshot_time <= rti.created_at
                               ORDER BY snapshot.snapshot_time DESC
                               LIMIT 1
                           ) odds ON TRUE
                           WHERE rti.real_ticket_id = %s""",
                        (rtid,),
                    )
                    all_ritems = cur.fetchall()

                real_detail = _resolve_ticket_items(
                    [
                        {
                            "match_id": item[0],
                            "option_code": item[1],
                            "sp_value": item[2],
                            "play_type": item[3],
                            "handicap": item[4],
                        }
                        for item in all_ritems
                    ],
                    full_result_map,
                )
                if real_detail is None:
                    continue

                stake = rticket["total_amount"]
                pass_type = rticket["pass_type"]
                multiple = rticket["multiple"]
                prize = calculate_winning_prize(real_detail, pass_type, multiple)
                real_ticket_won = prize > 0

                tax = _calculate_tax(prize)
                net_prize = prize - tax
                profit_loss = net_prize - stake
                roi = profit_loss / stake if stake > 0 else 0.0

                settlement_id = create_settlement(
                    conn,
                    {
                        "ticket_source": "real",
                        "ticket_id": rtid,
                        "settle_time": utc_now_iso(),
                        "is_won": real_ticket_won,
                        "stake_amount": stake,
                        "prize_amount": prize,
                        "tax_amount": tax,
                        "net_prize": net_prize,
                        "profit_loss": profit_loss,
                        "roi": roi,
                        "settlement_detail_json": {
                            "source": "real",
                            "items": real_detail,
                            "pass_type": pass_type,
                            "multiple": multiple,
                            "all_won": all(item["is_won"] for item in real_detail),
                            "has_winning_combination": real_ticket_won,
                        },
                    },
                )

                if settlement_id:
                    # Bankroll: credit prize for winning real tickets
                    if real_ticket_won and net_prize > 0:
                        create_bankroll_transaction(
                            conn,
                            {
                                "account_type": "real",
                                "transaction_type": "prize",
                                "amount": net_prize,
                                "related_ticket_id": rtid,
                                "remark": f"实票 #{rtid} 中奖 {prize:.2f}, 税后 {net_prize:.2f}",
                            },
                        )
                    # Lost: no transaction (stake paid at store, no digital movement)

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
            "simulator_settled": simulator_settled,
            "real_settled": real_settled,
            "total_prize": round(total_prize, 2),
            "legacy_repairs": legacy_repairs,
        }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
