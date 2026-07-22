"""League standings collection job.

Daily job (03:00) using ApiFootballClient.
Fetches standings for active competitions and stores in season_standings_snapshots.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.api_football_client import ApiFootballClient
from scripts.feature_storage import store_season_standings_snapshot


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def run(dry_run: bool = False, season: int | None = None) -> dict[str, Any]:
    """Collect league standings from API-Football.

    Args:
        dry_run: If True, don't write to DB.
        season: Season year to query. Defaults to 2024 (latest available on
                free tier; 2025/2026 require paid plan).

    Returns:
        Summary dict.
    """
    import os

    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}

    # Free tier only allows 2022-2024 seasons for standings/injuries.
    # 2025/2026 require a paid API-Football plan.
    if season is None:
        season = 2024

    client = ApiFootballClient(api_key=api_key)
    standings_stored = 0
    competitions_processed = 0
    errors = 0

    try:
        with get_db() as conn:
            # Get competitions with API-Football league IDs
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cs.id, s.season_code, c.id as comp_id,
                           c.competition_name_cn, c.competition_code
                    FROM competition_seasons cs
                    JOIN competitions c ON c.id = cs.competition_id
                    JOIN seasons s ON s.id = cs.season_id
                    LIMIT 10
                    """
                )
                competitions = [(r[0], r[1], r[2], r[3], r[4]) for r in cur.fetchall()]

            if not competitions:
                return {"status": "ok", "note": "no competitions found"}
            print(f"[collect_standings] using season={season}, {len(competitions)} competitions")

            snap_time = _now()

            for cs_id, _season_code, _comp_id, comp_name, comp_code in competitions:
                try:
                    # Extract API-Football league ID from competition_code
                    api_league_id: int | None = None
                    if comp_code and comp_code.startswith("apifootball:"):
                        try:
                            api_league_id = int(comp_code.split(":")[1])
                        except ValueError, IndexError:
                            pass

                    if api_league_id is None:
                        print(
                            f"[collect_standings] cannot resolve API league ID "
                            f"for {comp_name} (code={comp_code}), skipping"
                        )
                        continue

                    # Fetch standings from API-Football
                    data = client.get_standings(league=api_league_id, season=season)

                    # API-Football returns: [{ league: { standings: [[...]] } }]
                    for entry in data:
                        league_data = entry.get("league", {})
                        standings_groups = league_data.get("standings", [])

                        for group in standings_groups:
                            for row in group:
                                team_info = row.get("team", {})
                                team_name = team_info.get("name", "")

                                # Resolve team_id via aliases
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

                                all_stats = row.get("all", {})
                                home_stats = row.get("home", {})
                                away_stats = row.get("away", {})

                                if not dry_run:
                                    store_season_standings_snapshot(
                                        conn,
                                        {
                                            "competition_season_id": cs_id,
                                            "team_id": team_id,
                                            "snapshot_time": snap_time,
                                            "round_no": None,
                                            "rank": row.get("rank"),
                                            "played": all_stats.get("played"),
                                            "won": all_stats.get("win"),
                                            "drawn": all_stats.get("draw"),
                                            "lost": all_stats.get("lose"),
                                            "goals_for": (all_stats.get("goals") or {}).get("for"),
                                            "goals_against": (all_stats.get("goals") or {}).get(
                                                "against"
                                            ),
                                            "goal_difference": row.get("goalsDiff"),
                                            "points": row.get("points"),
                                            "home_points": home_stats.get("win", 0) * 3
                                            + home_stats.get("draw", 0)
                                            if home_stats
                                            else None,
                                            "away_points": away_stats.get("win", 0) * 3
                                            + away_stats.get("draw", 0)
                                            if away_stats
                                            else None,
                                            "source_name": "api-football",
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
        "api_calls_used": client.call_count_today,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    season = None
    for arg in sys.argv:
        if arg.startswith("--season="):
            season = int(arg.split("=")[1])
    result = run(dry_run=dry, season=season)
    print(result)
