"""Generate weekly and monthly review rows from daily_reviews."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_today
from scripts.real_ticket_storage import upsert_monthly_review, upsert_weekly_review
from scripts.review_generator import monthly_summary, weekly_summary
from scripts.upset.reports import generate_report


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


def _aggregate_review_rows(rows: list[tuple]) -> dict[str, float | int]:
    """Aggregate daily P&L into weighted ROI, drawdown, and losing streaks."""
    total_stake = 0.0
    total_prize = 0.0
    profit_loss = 0.0
    bankroll = 0.0
    peak = 0.0
    max_drawdown = 0.0
    losing_days = 0
    current_losing_streak = 0
    longest_losing_streak = 0

    for _review_date, stake, prize, daily_profit in sorted(rows, key=lambda row: str(row[0])):
        stake_value = float(stake or 0)
        prize_value = float(prize or 0)
        profit_value = float(daily_profit or 0)
        total_stake += stake_value
        total_prize += prize_value
        profit_loss += profit_value
        bankroll += profit_value
        peak = max(peak, bankroll)
        max_drawdown = max(max_drawdown, peak - bankroll)

        if profit_value < 0:
            losing_days += 1
            current_losing_streak += 1
            longest_losing_streak = max(longest_losing_streak, current_losing_streak)
        else:
            current_losing_streak = 0

    roi = profit_loss / total_stake if total_stake > 0 else 0.0
    return {
        "total_stake": round(total_stake, 2),
        "total_prize": round(total_prize, 2),
        "profit_loss": round(profit_loss, 2),
        "roi": round(roi, 4),
        "max_drawdown": round(max_drawdown, 2),
        "losing_days_count": losing_days,
        "longest_losing_streak": longest_losing_streak,
    }


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
                SELECT review_date, actual_stake, real_prize, real_profit_loss
                FROM daily_reviews
                WHERE review_date BETWEEN %s AND %s
                ORDER BY review_date
                """,
                (start, end),
            )
            aggregate = _aggregate_review_rows(cur.fetchall())

        data = {
            "week_start": start,
            "week_end": end,
            "total_stake": aggregate["total_stake"],
            "total_prize": aggregate["total_prize"],
            "profit_loss": aggregate["profit_loss"],
            "roi": aggregate["roi"],
            "max_drawdown": aggregate["max_drawdown"],
            "losing_days_count": aggregate["losing_days_count"],
            "simulation_vs_real_gap": "详见日复盘偏离率",
            "strategy_suggestion": "延续预算纪律，优先复核高偏离玩法。",
        }
        data["strategy_adjustment"] = weekly_summary(data)
        review_id = upsert_weekly_review(conn, data)
        upset_report = generate_report(
            conn,
            report_type="weekly",
            start=start,
            end=end,
        )

    return {
        "status": "ok",
        "review_id": review_id,
        "week_start": start,
        "week_end": end,
        "upset_report": upset_report,
    }


def run_monthly(month: str | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Generate a monthly review from daily review aggregates."""
    if dry_run:
        return {"status": "dry_run", "message": "generate monthly review (dry run)"}

    target_month = month or _previous_month()

    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT review_date, actual_stake, real_prize, real_profit_loss
                FROM daily_reviews
                WHERE to_char(review_date, 'YYYY-MM') = %s
                ORDER BY review_date
                """,
                (target_month,),
            )
            aggregate = _aggregate_review_rows(cur.fetchall())

        data = {
            "month": target_month,
            "total_stake": aggregate["total_stake"],
            "total_prize": aggregate["total_prize"],
            "profit_loss": aggregate["profit_loss"],
            "roi": aggregate["roi"],
            "max_drawdown": aggregate["max_drawdown"],
            "longest_losing_streak": aggregate["longest_losing_streak"],
            "best_strategy_pool": "待样本积累",
            "worst_strategy_pool": "待样本积累",
            "model_calibration_score": 0,
            "next_month_plan": "控制单日预算，优先提升官方赔率与特征快照完整率。",
        }
        data["summary_text"] = monthly_summary(data)
        review_id = upsert_monthly_review(conn, data)
        month_start = f"{target_month}-01"
        month_end = (
            date.fromisoformat(month_start).replace(day=28) + timedelta(days=4)
        ).replace(day=1) - timedelta(days=1)
        upset_report = generate_report(
            conn,
            report_type="monthly",
            start=month_start,
            end=month_end.isoformat(),
        )

    return {
        "status": "ok",
        "review_id": review_id,
        "month": target_month,
        "upset_report": upset_report,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    if "--monthly" in sys.argv:
        print(run_monthly(dry_run=dry))
    else:
        print(run_weekly(dry_run=dry))
