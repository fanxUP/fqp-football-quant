"""Job: crawl traditional football lottery (14场/任九) data.

Fetches current issue match pool and draw info via Playwright.
Called by the scheduler every few hours during sale periods.
Can also be invoked manually: python -m scripts.jobs.crawl_traditional_lottery
"""

from __future__ import annotations

import sys

from scripts.official_crawler import crawl_traditional_lottery


def run() -> dict:
    """Fetch and store traditional lottery (14场/任九) data."""
    print("[crawl_traditional_lottery] running…")
    result = crawl_traditional_lottery()
    print(f"[crawl_traditional_lottery] done: {result}")
    return result


if __name__ == "__main__":
    result = run()
    if result["status"] != "ok":
        sys.exit(1)
