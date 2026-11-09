"""Job: crawl traditional football lottery (14场/任九) data.

Fetches current issue match pool and draw info via Playwright.
Called by the scheduler every few hours during sale periods.
Can also be invoked manually: python -m scripts.jobs.crawl_traditional_lottery
"""

from __future__ import annotations

import logging
import sys

from scripts.official_crawler import crawl_traditional_lottery
from scripts.sporttery_pool_schedule import refresh_current_pool_schedule
from scripts.sporttery_schedule_notices import refresh_pool_notices

logger = logging.getLogger(__name__)


def run() -> dict:
    """Fetch and store traditional lottery (14场/任九) data."""
    print("[crawl_traditional_lottery] running…")
    result = crawl_traditional_lottery()
    print(f"[crawl_traditional_lottery] done: {result}")
    return result


def run_schedule() -> dict:
    try:
        notice_count = refresh_pool_notices()
    except Exception:
        logger.exception("Traditional notices unavailable; keeping confirmed evidence")
        notice_count = None
    result = refresh_current_pool_schedule()
    result["schedule_notices"] = notice_count
    if notice_count is None:
        result["status"] = "partial"
    return result


if __name__ == "__main__":
    result = run()
    if result["status"] != "ok":
        sys.exit(1)
