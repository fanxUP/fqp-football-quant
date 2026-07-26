"""Periodic job: settle finished matches — fetch results from sporttery.cn.

Called by the scheduler every 30 minutes.
Checks yesterday + today for newly-available results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from scripts.business_time import business_today
from scripts.official_crawler import crawl_official_results


def run(now: datetime | None = None) -> dict:
    """Fetch a four-day window so delayed and early-morning results are recovered."""
    today = business_today(now).isoformat()
    begin_date = (business_today(now) - timedelta(days=3)).isoformat()

    print(f"[settle_finished_matches] fetching results {begin_date} → {today}")
    result = crawl_official_results(begin_date=begin_date, end_date=today)
    print(f"[settle_finished_matches] done: {result}")
    return result


if __name__ == "__main__":
    result = run()
    if result["status"] != "ok":
        import sys

        sys.exit(1)
