"""Weather data collection job.

Daily job (09:00, 15:00) using OpenMeteoClient.
Fetches weather forecasts for upcoming match stadiums and stores in
match_weather_snapshots.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.features.build_weather_features import build_weather_for_match
from scripts.features.stadium_resolver import resolve_match_stadium_location
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


def _run_impl(dry_run: bool = False) -> dict[str, Any]:
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
                SELECT id, home_team_name, away_team_name, kickoff_time, raw_json
                FROM official_matches
                WHERE sale_status = 'selling'
                  AND kickoff_time BETWEEN %(now)s AND %(cutoff)s
                ORDER BY kickoff_time
                LIMIT 50
                """,
                {"now": now, "cutoff": cutoff},
            )
            matches = [
                {
                    "id": r[0],
                    "home": r[1],
                    "away": r[2],
                    "kickoff": r[3],
                    "raw_json": r[4] or {},
                }
                for r in cur.fetchall()
            ]

        if not matches:
            return {"status": "ok", "note": "no upcoming matches in next 7 days"}

        client = OpenMeteoClient()
        success = 0
        skipped = 0
        failed = 0

        try:
            for match in matches:
                location = resolve_match_stadium_location(
                    conn,
                    match["raw_json"],
                    match["home"],
                )
                if not location:
                    print(f"[weather] unresolved stadium for match {match['id']}, skipping")
                    skipped += 1
                    continue

                if dry_run:
                    success += 1
                    continue

                result = build_weather_for_match(
                    conn=conn,
                    match_id=match["id"],
                    kickoff_time=match["kickoff"],
                    stadium_lat=location["latitude"],
                    stadium_lon=location["longitude"],
                    stadium_id=location["stadium_id"],
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


def run(dry_run: bool = False) -> dict[str, Any]:
    """Run weather collection and persist its multi-agent execution record."""
    run_id = start_tracked_job("weather_collection", "feature_agent", {"dry_run": dry_run})
    try:
        result = _run_impl(dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
