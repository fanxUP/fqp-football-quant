"""Recurring job: crawl official match schedule from sporttery.cn.

Uses uniform API (WAF-free) as primary source, falls back to V1 API.
Called by the scheduler every 30 minutes because Sporttery can publish or reopen
matches after the first snapshot of the business day.
Can also be invoked manually: python -m scripts.jobs.crawl_official_schedule [YYYY-MM-DD]
"""

from __future__ import annotations

import sys
from datetime import datetime

from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.official_crawler import crawl_official_schedule_v2


def run(business_date: str | None = None) -> dict:
    """Fetch and store today's official match schedule.

    Uses uniform API (V2, no WAF) with fallback to legacy V1.

    Args:
        business_date: Date in YYYY-MM-DD format. Defaults to today.
    """
    if business_date is None:
        business_date = datetime.now().strftime("%Y-%m-%d")

    print(f"[crawl_official_schedule] running for {business_date}")
    run_id = start_tracked_job("official_schedule", "data_agent", {"business_date": business_date})
    try:
        result = crawl_official_schedule_v2(business_date)
        finish_tracked_job(run_id, "completed" if result.get("status") == "ok" else "failed", result)
        print(f"[crawl_official_schedule] done: {result}")
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    result = run(business_date=date_arg)
    if result["status"] != "ok":
        sys.exit(1)
