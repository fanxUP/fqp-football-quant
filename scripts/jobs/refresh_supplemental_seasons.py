"""Refresh isolated third-party season data and derived standings."""

from __future__ import annotations

import fcntl
from pathlib import Path

from scripts.jobs.build_supplemental_standings import run as build_standings
from scripts.season_crawler import LEAGUE_IDS, crawl_league_full

LOCK_PATH = Path(".runtime/supplemental_refresh.lock")


def run() -> dict:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w") as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped", "reason": "refresh_already_running"}
        results = []
        for league_name, league_id in LEAGUE_IDS.items():
            results.append(crawl_league_full(league_name, league_id))
        standings = build_standings()
        return {"status": "ok", "leagues": results, "standings": standings}


if __name__ == "__main__":
    print(run())
