"""Weather data collection job.

Daily job (09:00, 15:00) using OpenMeteoClient.
Fetches weather forecasts for upcoming match stadiums and stores in
match_weather_snapshots.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.features.build_weather_features import build_weather_for_match
from scripts.openmeteo_client import OpenMeteoClient


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_stadium_coords(conn: Any, stadium_id: int) -> tuple[float, float] | None:
    """Get stadium lat/lon from DB."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT latitude, longitude FROM stadiums WHERE id = %s",
            (stadium_id,),
        )
        row = cur.fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    return (float(row[0]), float(row[1]))


def run(dry_run: bool = False) -> dict[str, Any]:
    """Collect weather forecasts for upcoming matches.

    Finds matches within the next 7 days, resolves stadium coordinates,
    fetches Open-Meteo forecasts, and stores in match_weather_snapshots.

    Returns:
        Summary dict.
    """
    now = datetime.now()
    cutoff = now + timedelta(days=7)

    with get_db() as conn:
        # Get upcoming matches
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, home_team_name, away_team_name, kickoff_time
                FROM official_matches
                WHERE match_status = 'Selling'
                  AND kickoff_time BETWEEN %(now)s AND %(cutoff)s
                ORDER BY kickoff_time
                LIMIT 50
                """,
                {"now": now, "cutoff": cutoff},
            )
            matches = [
                {"id": r[0], "home": r[1], "away": r[2], "kickoff": r[3]} for r in cur.fetchall()
            ]

        if not matches:
            return {"status": "ok", "note": "no upcoming matches in next 7 days"}

        client = OpenMeteoClient()
        success = 0
        skipped = 0
        failed = 0

        try:
            for match in matches:
                # Try to resolve stadium from home team
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT s.id, s.latitude, s.longitude FROM stadiums s
                        JOIN team_stadium_history tsh ON tsh.stadium_id = s.id
                        JOIN team_aliases ta ON ta.team_id = tsh.team_id
                        WHERE ta.alias_name = %(name)s
                        ORDER BY tsh.start_date DESC LIMIT 1
                        """,
                        {"name": match["home"]},
                    )
                    row = cur.fetchone()

                lat = float(row[1]) if row and row[1] else None
                lon = float(row[2]) if row and row[2] else None
                stadium_id = row[0] if row else None

                if lat is None or lon is None:
                    skipped += 1
                    continue

                if dry_run:
                    success += 1
                    continue

                result = build_weather_for_match(
                    conn=conn,
                    match_id=match["id"],
                    kickoff_time=match["kickoff"],
                    stadium_lat=lat,
                    stadium_lon=lon,
                    stadium_id=stadium_id,
                    client=client,
                )
                if result and result.get("has_weather"):
                    success += 1
                elif result is None:
                    skipped += 1
                else:
                    failed += 1

        finally:
            client.close()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "matches_found": len(matches),
        "weather_fetched": success,
        "skipped": skipped,
        "failed": failed,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
