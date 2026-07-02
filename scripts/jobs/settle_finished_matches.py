"""Periodic job: settle finished matches — fetch results from sporttery.cn.

Called by the scheduler every 30 minutes.
Checks yesterday + today for newly-available results.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from scripts.official_crawler import crawl_official_results


def run() -> dict:
    """Fetch results for yesterday and today (catches early-finish matches)."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

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
