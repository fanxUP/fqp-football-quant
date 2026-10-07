"""Periodic job: fetch recent and outstanding official match results.

Called by the scheduler every 30 minutes.
Checks a recent four-day window and retries older dates blocking active tickets.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from scripts.business_time import business_today
from scripts.official_crawler import crawl_official_results


def run(now: datetime | None = None) -> dict:
    """Fetch recent results and bounded historical results needed for settlement."""
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
