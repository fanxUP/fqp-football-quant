"""Official odds snapshot job.

Hard rule: never overwrite historical odds snapshots (append-only).

Called by scheduler every 30 min during match hours, or ad-hoc via CLI.
"""

from __future__ import annotations

from datetime import datetime

from scripts.official_crawler import crawl_official_odds_snapshot


def run(dry_run: bool = False) -> dict:
    """Take an odds snapshot for all today's active matches.

    Args:
        dry_run: If True, only log what would happen without storing.
    """
    if dry_run:
        return {"status": "dry_run", "note": "odds snapshot would be taken for today's matches"}

    business_date = datetime.now().strftime("%Y-%m-%d")
    print(f"[run_official_odds_snapshot] taking snapshot for {business_date}")
    result = crawl_official_odds_snapshot(business_date)
    print(f"[run_official_odds_snapshot] done: {result}")
    return result


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    result = run(dry_run=dry)
    if result["status"] not in ("ok", "dry_run"):
        sys.exit(1)
