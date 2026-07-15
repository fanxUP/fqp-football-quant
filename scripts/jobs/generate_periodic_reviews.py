"""Generate weekly and monthly review rows from daily_reviews."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_today
from scripts.real_ticket_storage import upsert_monthly_review, upsert_weekly_review
from scripts.review_generator import monthly_summary, weekly_summary


def _previous_week(today: date | None = None) -> tuple[str, str]:
    base = today or business_today()
    this_monday = base - timedelta(days=base.weekday())
    week_start = this_monday - timedelta(days=7)
    week_end = week_start + timedelta(days=6)
    return week_start.isoformat(), week_end.isoformat()


def _previous_month(today: date | None = None) -> str:
    base = today or business_today()
    first_this_month = base.replace(day=1)
    last_previous_month = first_this_month - timedelta(days=1)
    return last_previous_month.strftime("%Y-%m")


def run_weekly(
    week_start: str | None = None,
    week_end: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Generate a weekly review from daily review aggregates."""
    if dry_run:
        return {"status": "dry_run", "message": "generate weekly review (dry run)"}

    start, end = (week_start, week_end) if week_start and week_end else _previous_week()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(actual_stake), 0),
                    COALESCE(SUM(real_prize), 0),
                    COALESCE(SUM(real_profit_loss), 0),
                    COALESCE(AVG(real_roi), 0),
                    COALESCE(MIN(real_profit_loss), 0),
                    COUNT(*) FILTER (WHERE real_profit_loss < 0)
                FROM daily_reviews
                WHERE review_date BETWEEN %s AND %s
                """,
                (start, end),
            )
            stake, prize, profit_loss, roi, max_drawdown, losing_days = cur.fetchone()

        data = {
            "week_start": start,
            "week_end": end,
            "total_stake": float(stake or 0),
            "total_prize": float(prize or 0),
            "profit_loss": float(profit_loss or 0),
            "roi": float(roi or 0),
            "max_drawdown": abs(float(max_drawdown or 0)),
            "losing_days_count": int(losing_days or 0),
            "simulation_vs_real_gap": "详见日复盘偏离率",
            "strategy_suggestion": "延续预算纪律，优先复核高偏离玩法。",
        }
        data["strategy_adjustment"] = weekly_summary(data)
        review_id = upsert_weekly_review(conn, data)

    return {"status": "ok", "review_id": review_id, "week_start": start, "week_end": end}


def run_monthly(month: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Generate a monthly review from daily review aggregates."""
    if dry_run:
        return {"status": "dry_run", "message": "generate monthly review (dry run)"}

    target_month = month or _previous_month()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(actual_stake), 0),
                    COALESCE(SUM(real_prize), 0),
                    COALESCE(SUM(real_profit_loss), 0),
                    COALESCE(AVG(real_roi), 0),
                    COALESCE(MIN(real_profit_loss), 0),
                    COUNT(*) FILTER (WHERE real_profit_loss < 0)
                FROM daily_reviews
                WHERE to_char(review_date, 'YYYY-MM') = %s
                """,
                (target_month,),
            )
            stake, prize, profit_loss, roi, max_drawdown, losing_days = cur.fetchone()

        data = {
            "month": target_month,
            "total_stake": float(stake or 0),
            "total_prize": float(prize or 0),
            "profit_loss": float(profit_loss or 0),
            "roi": float(roi or 0),
            "max_drawdown": abs(float(max_drawdown or 0)),
            "longest_losing_streak": int(losing_days or 0),
            "best_strategy_pool": "待样本积累",
            "worst_strategy_pool": "待样本积累",
            "model_calibration_score": 0,
            "next_month_plan": "控制单日预算，优先提升官方赔率与特征快照完整率。",
        }
        data["summary_text"] = monthly_summary(data)
        review_id = upsert_monthly_review(conn, data)

    return {"status": "ok", "review_id": review_id, "month": target_month}


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    if "--monthly" in sys.argv:
        print(run_monthly(dry_run=dry))
    else:
        print(run_weekly(dry_run=dry))
