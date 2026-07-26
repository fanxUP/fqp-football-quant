"""Daily review generation job.

Aggregates the previous day's activity into the daily_reviews table.
Runs at 23:30 daily — reviews yesterday's data (today incomplete).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.business_time import business_yesterday
from scripts.real_ticket_storage import upsert_daily_review
from scripts.review_generator import daily_summary
from scripts.upset.reports import generate_report


def _yesterday(now: datetime | None = None) -> str:
    return business_yesterday(now or datetime.now(UTC)).isoformat()


def _settlement_totals(rows: list[tuple]) -> dict[str, dict[str, float]]:
    """Aggregate settlement P&L using weighted ROI instead of averaging ticket ROI."""
    totals = {
        "simulation": {"prize": 0.0, "profit_loss": 0.0, "roi": 0.0},
        "real": {"prize": 0.0, "profit_loss": 0.0, "roi": 0.0},
    }
    for source, stake, prize, profit_loss, _average_roi in rows:
        if source not in totals:
            continue
        stake_value = float(stake or 0)
        profit_value = float(profit_loss or 0)
        totals[source] = {
            "prize": float(prize or 0),
            "profit_loss": profit_value,
            "roi": profit_value / stake_value if stake_value > 0 else 0.0,
        }
    return totals


def _run_impl(review_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Generate daily review for the given date (default: yesterday)."""
    if dry_run:
        return {"status": "dry_run", "message": "generate daily review (dry run)"}

    date = review_date or _yesterday()

    with get_db() as conn:
        # 1. Count official matches for the date
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM official_matches WHERE business_date = %s",
                (date,),
            )
            official_count = cur.fetchone()[0] or 0

        # 2. Count analyzable matches (have feature snapshots)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT fs.match_id)
                FROM match_feature_snapshots fs
                JOIN official_matches m ON m.id = fs.match_id
                WHERE m.business_date = %s
                  AND fs.snapshot_time < m.kickoff_time
                """,
                (date,),
            )
            analyzable_count = cur.fetchone()[0] or 0

        # 3. Count recommended matches (have predictions)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT mp.match_id)
                FROM model_predictions mp
                JOIN official_matches m ON m.id = mp.match_id
                WHERE m.business_date = %s
                  AND mp.predict_time < m.kickoff_time
                  AND mp.validation_status = 'valid'
                """,
                (date,),
            )
            recommended_count = cur.fetchone()[0] or 0

        # 4. Count simulation tickets created on this date
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM simulation_tickets
                   WHERE (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s
                     AND ticket_status IN ('generated', 'activated', 'settled')""",
                (date,),
            )
            sim_ticket_count = cur.fetchone()[0] or 0

        # 5. Count real tickets purchased on this date
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) FROM real_tickets
                   WHERE (purchase_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s""",
                (date,),
            )
            real_ticket_count = cur.fetchone()[0] or 0

        # 6. Get suggested stakes (sum of simulation tickets)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(suggested_stake), 0) FROM simulation_tickets
                   WHERE (created_at AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s
                     AND ticket_status IN ('generated', 'activated', 'settled')""",
                (date,),
            )
            suggested_stake = float(cur.fetchone()[0] or 0)

        # 7. Get actual stakes (sum of real tickets)
        with conn.cursor() as cur:
            cur.execute(
                """SELECT COALESCE(SUM(total_amount), 0) FROM real_tickets
                   WHERE (purchase_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s""",
                (date,),
            )
            actual_stake = float(cur.fetchone()[0] or 0)

        # 8. Get settlement P&L for the date
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ticket_source,
                       COALESCE(SUM(stake_amount), 0),
                       COALESCE(SUM(prize_amount), 0),
                       COALESCE(SUM(profit_loss), 0),
                       AVG(roi)
                FROM ticket_settlements
                WHERE (settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s
                GROUP BY ticket_source
                """,
                (date,),
            )
            settlement_rows = cur.fetchall()

        settlement_totals = _settlement_totals(settlement_rows)
        simulation = settlement_totals["simulation"]
        real = settlement_totals["real"]
        sim_prize = simulation["prize"]
        sim_pl = simulation["profit_loss"]
        sim_roi = simulation["roi"]
        real_prize = real["prize"]
        real_pl = real["profit_loss"]
        real_roi = real["roi"]

        # 9. Budget usage rate (daily budget = 500)
        budget_usage_rate = actual_stake / 500.0 if actual_stake > 0 else 0.0

        # 10. Max single ticket loss
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COALESCE(MIN(profit_loss), 0)
                FROM ticket_settlements
                WHERE (settle_time AT TIME ZONE 'UTC' AT TIME ZONE 'Asia/Shanghai')::date = %s
                """,
                (date,),
            )
            max_loss = float(cur.fetchone()[0] or 0)

        # 11. User deviation rate
        if suggested_stake > 0:
            deviation_rate = abs(actual_stake - suggested_stake) / suggested_stake
        else:
            deviation_rate = 0.0

        # 12. Get top error types for the date
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT error_type, COUNT(*) AS cnt
                FROM prediction_error_analysis pea
                JOIN official_matches m ON m.id = pea.match_id
                WHERE m.business_date = %s
                GROUP BY error_type
                ORDER BY cnt DESC
                LIMIT 3
                """,
                (date,),
            )
            error_rows = cur.fetchall()
        top_errors = ", ".join(f"{r[0]}×{r[1]}" for r in error_rows) if error_rows else ""

        # 13. Generate summary text
        summary = daily_summary(
            {
                "review_date": date,
                "official_match_count": official_count,
                "analyzable_match_count": analyzable_count,
                "recommended_match_count": recommended_count,
                "simulation_ticket_count": sim_ticket_count,
                "real_ticket_count": real_ticket_count,
                "suggested_stake": suggested_stake,
                "actual_stake": actual_stake,
                "simulation_profit_loss": sim_pl,
                "real_profit_loss": real_pl,
                "simulation_roi": sim_roi,
                "real_roi": real_roi,
                "budget_usage_rate": budget_usage_rate,
                "deviation_rate": deviation_rate,
                "top_error_types": top_errors,
            }
        )

        # 14. Upsert daily review
        review_id = upsert_daily_review(
            conn,
            {
                "review_date": date,
                "official_match_count": official_count,
                "analyzable_match_count": analyzable_count,
                "recommended_match_count": recommended_count,
                "simulation_ticket_count": sim_ticket_count,
                "real_ticket_count": real_ticket_count,
                "suggested_stake": suggested_stake,
                "actual_stake": actual_stake,
                "simulation_prize": sim_prize,
                "real_prize": real_prize,
                "simulation_profit_loss": sim_pl,
                "real_profit_loss": real_pl,
                "simulation_roi": sim_roi,
                "real_roi": real_roi,
                "budget_usage_rate": budget_usage_rate,
                "max_single_ticket_loss": max_loss,
                "max_single_match_exposure": 0,
                "summary_text": summary,
                "next_day_adjustment": "",
            },
        )
        upset_report = generate_report(
            conn,
            report_type="daily",
            start=date,
            end=date,
        )

    return {
        "status": "ok",
        "review_id": review_id,
        "review_date": date,
        "official_match_count": official_count,
        "simulation_ticket_count": sim_ticket_count,
        "real_ticket_count": real_ticket_count,
        "summary": summary,
        "upset_report": upset_report,
    }


def run(review_date: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Generate review and persist its multi-agent execution record."""
    run_id = start_tracked_job(
        "daily_review", "review_agent", {"review_date": review_date, "dry_run": dry_run}
    )
    try:
        result = _run_impl(review_date=review_date, dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    date_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    result = run(review_date=date_arg, dry_run=dry)
    print(result)
