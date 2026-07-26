"""Worker entrypoint — single owner of high-frequency odds dispatch.

The worker checks every minute; the durable capture policy decides whether an
opening, 30-minute, retry, or exact-kickoff snapshot is actually due.
"""

from __future__ import annotations

import os
import time

from scripts.local.worker_heartbeat import write_worker_heartbeat

POLL_INTERVAL_SECONDS = 60


def _official_source_enabled() -> bool:
    return os.getenv("OFFICIAL_SOURCE_ENABLED", "true").lower() == "true"


def run_once() -> dict:
    """Publish liveness and dispatch one idempotent odds-capture check."""
    write_worker_heartbeat()
    if os.getenv("FQP_ODDS_DISPATCH_OWNER", "scheduler").lower() != "worker":
        return {"status": "skipped", "reason": "scheduler_owns_odds_dispatch"}
    if not _official_source_enabled():
        return {"status": "skipped", "reason": "official_source_disabled"}

    from scripts.jobs.run_official_odds_snapshot import run

    result = run()
    write_worker_heartbeat()
    return result


def main() -> None:
    print("FQP worker started.")
    print("Worker owns minute-level odds dispatch.")

    while True:
        try:
            result = run_once()
            print(f"[worker] odds dispatch result: {result}")
        except Exception as e:
            print(f"[worker] odds dispatch error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
