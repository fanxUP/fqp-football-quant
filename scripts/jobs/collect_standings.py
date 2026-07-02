"""League standings collection job.

Daily job (03:00) using FootballDataClient.
Fetches standings for active competitions and stores in season_standings_snapshots.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.feature_storage import store_season_standings_snapshot
from scripts.football_data_client import FootballDataClient


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run(dry_run: bool = False) -> dict[str, Any]:
    """Collect league standings from football-data.org.

    Returns:
        Summary dict.
    """
    import os

    api_key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    if not api_key:
        return {"status": "error", "message": "FOOTBALL_DATA_API_KEY not set"}

    client = FootballDataClient(api_key=api_key)
    standings_stored = 0
    competitions_processed = 0
    errors = 0

    try:
        with get_db() as conn:
            # Get active competition seasons with football-data.org IDs
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cs.id, cs.season_code, c.id as comp_id, c.competition_name
                    FROM competition_seasons cs
                    JOIN competitions c ON c.id = cs.competition_id
                    WHERE cs.is_active = true
                    LIMIT 10
                    """
                )
                competitions = [(r[0], r[1], r[2], r[3]) for r in cur.fetchall()]

            if not competitions:
                return {"status": "ok", "note": "no active competitions found"}

            snap_time = _now()

            for cs_id, _season_code, comp_id, comp_name in competitions:
                try:
                    data = client.get_competition_standings(comp_id)
                    standings = data.get("standings", [])

                    for table in standings:
                        table_type = table.get("type", "")  # TOTAL, HOME, AWAY
                        if table_type != "TOTAL":
                            continue

                        for row in table.get("table", []):
                            team_info = row.get("team", {})
                            team_name = team_info.get("name", "")

                            # Resolve team_id
                            with conn.cursor() as cur:
                                cur.execute(
                                    """
                                    SELECT t.id FROM teams t
                                    JOIN team_aliases ta ON ta.team_id = t.id
                                    WHERE ta.alias_name = %(name)s
                                    LIMIT 1
                                    """,
                                    {"name": team_name},
                                )
                                tr = cur.fetchone()
                            if not tr:
                                continue
                            team_id = tr[0]

                            if not dry_run:
                                store_season_standings_snapshot(
                                    conn,
                                    {
                                        "competition_season_id": cs_id,
                                        "team_id": team_id,
                                        "snapshot_time": snap_time,
                                        "round_no": None,
                                        "rank": row.get("position"),
                                        "played": row.get("playedGames"),
                                        "won": row.get("won"),
                                        "drawn": row.get("draw"),
                                        "lost": row.get("lost"),
                                        "goals_for": row.get("goalsFor"),
                                        "goals_against": row.get("goalsAgainst"),
                                        "goal_difference": row.get("goalDifference"),
                                        "points": row.get("points"),
                                        "home_points": None,
                                        "away_points": None,
                                        "source_name": "football-data.org",
                                        "source_confidence": 0.85,
                                        "raw_json": row,
                                    },
                                )
                                standings_stored += 1

                    competitions_processed += 1

                except Exception as e:
                    print(f"[collect_standings] error for {comp_name}: {e}")
                    errors += 1
                    continue

    finally:
        client.close()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "competitions_processed": competitions_processed,
        "standings_stored": standings_stored,
        "errors": errors,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
