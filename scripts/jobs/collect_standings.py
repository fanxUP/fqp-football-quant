"""Compatibility entrypoint for verified current-season standings collection.

The former implementation queried API-SPORTS season 2024 and wrote those rows
into current competition-season records. That stale cross-season path is now
closed; scheduler and manual callers use official league sources only.
"""

from __future__ import annotations

from typing import Any

from scripts.jobs.collect_official_standings import run as collect_official_standings
from scripts.jobs.seed_official_team_aliases import run as seed_official_team_aliases


def run(dry_run: bool = False, season: int | None = None) -> dict[str, Any]:
    """Collect verified standings; ``season`` remains for CLI compatibility."""
    alias_result = {"status": "skipped"} if dry_run else seed_official_team_aliases()
    result = collect_official_standings(dry_run=dry_run)
    return {
        **result,
        "alias_seed": alias_result,
        "requested_season": season,
        "source_policy": "verified_official_current_season",
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    requested_season = next(
        (int(arg.split("=", 1)[1]) for arg in sys.argv if arg.startswith("--season=")),
        None,
    )
    print(run(dry_run=dry, season=requested_season))
