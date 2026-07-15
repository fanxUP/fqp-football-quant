"""Periodic job: settle finished matches — fetch results from sporttery.cn.

Called by the scheduler every 30 minutes.
Checks yesterday + today for newly-available results.
"""

from __future__ import annotations

from datetime import datetime

from scripts.business_time import business_today, business_yesterday
from scripts.official_crawler import crawl_official_results


def run(now: datetime | None = None) -> dict:
    """Fetch results for yesterday and today (catches early-finish matches)."""
    today = business_today(now).isoformat()
    yesterday = business_yesterday(now).isoformat()

    # Fetch yesterday's results (most matches finish on same day)
    print(f"[settle_finished_matches] fetching results {yesterday} → {today}")
    result = crawl_official_results(begin_date=yesterday, end_date=today)
    print(f"[settle_finished_matches] done: {result}")
    return result


if __name__ == "__main__":
    result = run()
    if result["status"] != "ok":
        import sys

        sys.exit(1)
