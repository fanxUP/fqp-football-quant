"""Official odds snapshot job.

Hard rule: never overwrite historical odds snapshots (append-only).

Called by scheduler every 30 min during match hours, or ad-hoc via CLI.
"""

from __future__ import annotations

from datetime import datetime

from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
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
    run_id = start_tracked_job("official_odds_snapshot", "data_agent", {"business_date": business_date})
    try:
        result = crawl_official_odds_snapshot(business_date)
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise
    finish_tracked_job(run_id, "completed" if result.get("status") == "ok" else "failed", result)
    print(f"[run_official_odds_snapshot] done: {result}")
    return result


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    result = run(dry_run=dry)
    if result["status"] not in ("ok", "dry_run"):
        sys.exit(1)
