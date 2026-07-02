"""Worker entrypoint — long-running odds polling loop.

Runs in the Worker container. Every 30 minutes, takes an odds snapshot
for all today's active matches from sporttery.cn.

In the future, this will be replaced by more sophisticated crawler tasks
(orchestrated by the scheduler + Codex agents).
"""

from __future__ import annotations

import os
import time
from datetime import datetime

POLL_INTERVAL_SECONDS = 30 * 60  # 30 minutes


def _official_source_enabled() -> bool:
    return os.getenv("OFFICIAL_SOURCE_ENABLED", "true").lower() == "true"


def main() -> None:
    print("FQP worker started.")
    if not _official_source_enabled():
        print("Official source disabled (OFFICIAL_SOURCE_ENABLED != true). Worker idle.")
        while True:
            print(f"worker heartbeat: {datetime.now().isoformat(timespec='seconds')}")
            time.sleep(3600)

    print(f"Worker odds polling: every {POLL_INTERVAL_SECONDS // 60} minutes.")

    while True:
        try:
            from scripts.official_crawler import crawl_official_odds_snapshot

            today = datetime.now().strftime("%Y-%m-%d")
            print(
                f"\n[worker] polling odds for {today} at {datetime.now().isoformat(timespec='seconds')}"
            )
            result = crawl_official_odds_snapshot(today)
            print(f"[worker] odds snapshot result: {result}")
        except Exception as e:
            print(f"[worker] odds snapshot error: {e}")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
