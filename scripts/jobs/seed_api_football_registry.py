"""校准 API-Football 联赛标识和球队别名基础数据。"""

from __future__ import annotations

from typing import Any

from scripts.jobs.seed_competitions import run as seed_competitions
from scripts.jobs.seed_team_aliases import run as seed_team_aliases


def run(dry_run: bool = False) -> dict[str, Any]:
    """先校准联赛/赛季，再校准球队别名；全程幂等。"""
    competition_result = seed_competitions(dry_run=dry_run)
    alias_result = seed_team_aliases(dry_run=dry_run)
    statuses = {
        str(competition_result.get("status", "ok")),
        str(alias_result.get("status", "ok")),
    }
    status = "error" if "error" in statuses else "dry_run" if dry_run else "ok"
    return {
        "status": status,
        "competitions": competition_result,
        "aliases": alias_result,
    }


if __name__ == "__main__":
    print(run())
