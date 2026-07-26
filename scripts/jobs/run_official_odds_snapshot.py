"""Official odds snapshot job.

Hard rule: never overwrite historical odds snapshots (append-only).

Called by the minute-level scheduler; the durable policy writes at opening,
every 30 minutes, retry windows, and kickoff only.
"""

from __future__ import annotations

from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.official_odds_capture import collect_due_official_odds


def run(dry_run: bool = False) -> dict:
    """Take an odds snapshot for all today's active matches.

    Args:
        dry_run: If True, only log what would happen without storing.
    """
    if dry_run:
        return {"status": "dry_run", "note": "odds snapshot would be taken for today's matches"}

    print("[run_official_odds_snapshot] dispatching due captures")
    run_id = start_tracked_job("official_odds_snapshot", "data_agent", {})
    try:
        result = collect_due_official_odds()
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
