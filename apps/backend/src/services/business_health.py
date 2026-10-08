"""Business integrity signals complementing the existing pipeline monitor."""

from __future__ import annotations

from typing import Any

from apps.backend.src.services.pipeline_status import get_pipeline_snapshot


def get_business_health(conn: Any) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(
            """
            WITH tickets AS (
                SELECT 'real'::text AS source, id, settlement_status AS status FROM real_tickets
                UNION ALL SELECT 'simulator', id, status FROM simulator_tickets
                UNION ALL SELECT 'simulation', id, ticket_status FROM simulation_tickets
            )
            SELECT
                COUNT(*) FILTER (WHERE t.status IN ('pending', 'generated', 'activated')
                                 AND s.id IS NOT NULL),
                COUNT(*) FILTER (WHERE t.status IN ('settled', 'won', 'lost') AND s.id IS NULL)
            FROM tickets t
            LEFT JOIN LATERAL (
                SELECT id FROM ticket_settlements
                WHERE ticket_source = t.source AND ticket_id = t.id LIMIT 1
            ) s ON TRUE
            """
        )
        pending_with_ledger, settled_without_ledger = cur.fetchone()
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT ticket_source, ticket_id FROM ticket_settlements
                GROUP BY ticket_source, ticket_id HAVING COUNT(*) > 1
            ) duplicates
            """
        )
        duplicate_ledgers = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM (
                SELECT account_id, related_ticket_id FROM bankroll_transactions
                WHERE transaction_type = 'prize' AND related_ticket_id IS NOT NULL
                GROUP BY account_id, related_ticket_id HAVING COUNT(*) > 1
            ) duplicates
            """
        )
        duplicate_prize_transactions = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM ticket_settlements s
            WHERE s.net_prize > 0
              AND EXISTS (SELECT 1 FROM bankroll_accounts a WHERE a.account_type = s.ticket_source)
              AND NOT EXISTS (
                  SELECT 1 FROM bankroll_transactions tx
                  JOIN bankroll_accounts a ON a.id = tx.account_id
                  WHERE a.account_type = s.ticket_source AND tx.related_ticket_id = s.ticket_id
                    AND tx.transaction_type = 'prize'
              )
            """
        )
        missing_prize_transactions = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM bankroll_accounts a
            JOIN LATERAL (
                SELECT balance_after FROM bankroll_transactions tx
                WHERE tx.account_id = a.id ORDER BY id DESC LIMIT 1
            ) last_tx ON TRUE
            WHERE a.current_balance IS DISTINCT FROM last_tx.balance_after
            """
        )
        balance_mismatches = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM ticket_settlements s
            JOIN bankroll_accounts a ON a.account_type = s.ticket_source
            JOIN LATERAL (
                SELECT SUM(amount) AS credited FROM bankroll_transactions tx
                WHERE tx.account_id = a.id AND tx.related_ticket_id = s.ticket_id
                  AND tx.transaction_type IN ('prize', 'settlement_adjustment')
            ) credit ON TRUE
            WHERE s.net_prize > 0 AND credit.credited IS NOT NULL
              AND ABS(credit.credited - s.net_prize) >= 0.01
            """
        )
        prize_amount_mismatches = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM real_tickets t
            WHERE t.confirm_status = 'confirmed' AND t.settlement_status = 'pending'
              AND EXISTS (SELECT 1 FROM real_ticket_items i WHERE i.real_ticket_id = t.id)
              AND NOT EXISTS (
                  SELECT 1 FROM real_ticket_items i
                  LEFT JOIN official_results r ON r.match_id = i.match_id
                  WHERE i.real_ticket_id = t.id
                    AND (r.match_id IS NULL OR r.result_status IS NULL
                      OR r.result_status NOT IN ('confirmed', 'void', 'refund', 'refunded')
                      OR r.updated_at IS NULL OR r.updated_at > NOW() - INTERVAL '90 minutes')
              )
            """
        )
        overdue_real_candidates = cur.fetchone()[0]
        cur.execute(
            """
            SELECT last_refreshed_at,
                   last_refreshed_at IS NULL OR last_refreshed_at < NOW() - INTERVAL '2 hours'
            FROM model_performance_scored_picks_state WHERE singleton = TRUE
            """
        )
        history = cur.fetchone()
    counts = {
        "pending_with_ledger": int(pending_with_ledger),
        "settled_without_ledger": int(settled_without_ledger),
        "duplicate_ledgers": int(duplicate_ledgers),
        "duplicate_prize_transactions": int(duplicate_prize_transactions),
        "missing_prize_transactions": int(missing_prize_transactions),
        "balance_mismatches": int(balance_mismatches),
        "prize_amount_mismatches": int(prize_amount_mismatches),
        "overdue_real_candidates": int(overdue_real_candidates),
    }
    critical_codes = {
        "settle_tickets",
        "settle_finished_matches",
        "refresh_model_performance_history",
    }
    jobs = [job for job in get_pipeline_snapshot(conn)["jobs"] if job["code"] in critical_codes]
    history_stale = not history or bool(history[1])
    needs_attention = (
        any(counts.values()) or history_stale or any(job["status"] != "success" for job in jobs)
    )
    return {
        "status": "attention" if needs_attention else "ok",
        "counts": counts,
        "history": {
            "stale": history_stale,
            "refreshedAt": history[0].isoformat() if history and history[0] else None,
        },
        "jobs": jobs,
        "note": "异常计数是核对线索；超时候选仍需核对玩法结果与让球数据，历史手工入账、可选账户及修正交易也需人工确认，不自动补发奖金。",
    }
