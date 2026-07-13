"""Injury/suspension data collection job.

Daily job (08:00) using ApiFootballClient.
Fetches injury data for active competitions and stores in
player_availability_snapshots.

Rate limit: ~10 API calls/day of 100 limit (free tier).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.api_football_client import ApiFootballClient
from scripts.feature_storage import (
    get_player_by_code,
    store_player,
    store_player_availability_snapshot,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# Position importance defaults from injury_impact_weights.yaml
POSITION_IMPORTANCE = {
    "GK": 0.95,
    "Goalkeeper": 0.95,
    "CB": 0.85,
    "Defender": 0.75,
    "DM": 0.82,
    "CM": 0.70,
    "AM": 0.76,
    "ST": 0.82,
    "Attacker": 0.78,
    "FB": 0.62,
    "W": 0.58,
    "SUB": 0.30,
}


def _position_importance(api_position: str) -> float:
    """Map API-Football position names to importance scores."""
    for key, val in POSITION_IMPORTANCE.items():
        if key.lower() in (api_position or "").lower():
            return val
    return 0.50


def _get_or_create_player(conn: Any, player_data: dict) -> int | None:
    """Find or create a player record, return player_id."""
    player_code = f"apifootball:{player_data.get('id')}"
    existing = get_player_by_code(conn, player_code)
    if existing:
        return existing["id"]

    return store_player(
        conn,
        {
            "player_code": player_code,
            "player_name_en": player_data.get("name", ""),
            "player_name_cn": "",
            "birth_date": player_data.get("birth", {}).get("date")
            if isinstance(player_data.get("birth"), dict)
            else None,
            "nationality": player_data.get("nationality", ""),
            "primary_position": player_data.get("position", ""),
            "secondary_positions": [],
            "preferred_foot": "",
            "height_cm": float(player_data.get("height", "").replace(" cm", ""))
            if player_data.get("height")
            else None,
        },
    )


def _resolve_team_id(conn: Any, team_name: str) -> int | None:
    """Map a team name to internal team_id via aliases."""
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
        row = cur.fetchone()
    return row[0] if row else None


def _run_impl(dry_run: bool = False, season: int | None = None) -> dict[str, Any]:
    """Collect injury data from API-Football for all active competitions.

    Args:
        dry_run: If True, fetch but don't store.
        season: Season year to query. Defaults to 2024 (latest available on
                free tier; 2025/2026 require paid plan).

    Returns:
        Summary dict.
    """
    import os

    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}

    # Free tier only allows 2022-2024 seasons for injury data.
    if season is None:
        season = 2024

    client = ApiFootballClient(api_key=api_key)
    injuries_collected = 0
    players_created = 0
    leagues_processed = 0
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
            print(f"[collect_injury] using season={season}, {len(competitions)} competitions")

            for cs_id, _season_code, _comp_id, comp_name, comp_code in competitions:
                try:
                    # Extract API-Football league ID from competition_code
                    # Format: "apifootball:113" → league_id = 113
                    api_league_id: int | None = None
                    if comp_code and comp_code.startswith("apifootball:"):
                        try:
                            api_league_id = int(comp_code.split(":")[1])
                        except (ValueError, IndexError):
                            pass

                    if api_league_id is None:
                        print(
                            f"[collect_injury] cannot resolve API league ID "
                            f"for {comp_name} (code={comp_code}), skipping"
                        )
                        continue

                    # Try to get injuries for this league+season
                    injuries = client.get_injuries(league=api_league_id, season=season)

                    if not injuries:
                        continue

                    leagues_processed += 1

                    for inj in injuries:
                        try:
                            player_info = inj.get("player", {})
                            team_info = inj.get("team", {})

                            team_name = team_info.get("name", "")
                            if not team_name:
                                continue

                            team_id = _resolve_team_id(conn, team_name)
                            if not team_id:
                                continue

                            # Create/find player
                            player_id = None
                            if not dry_run:
                                player_id = _get_or_create_player(conn, player_info)
                                if player_id:
                                    players_created += 1

                            # Build availability snapshot
                            availability_status = "injured"
                            injury_type = (
                                inj.get("injury", {}).get("type", "")
                                if isinstance(inj.get("injury"), dict)
                                else ""
                            )
                            (
                                inj.get("injury", {}).get("reason", "")
                                if isinstance(inj.get("injury"), dict)
                                else ""
                            )

                            pos = player_info.get("position", "")
                            pos_imp = _position_importance(pos)

                            snapshot = {
                                "player_id": player_id or 0,
                                "team_id": team_id,
                                "competition_season_id": cs_id,
                                "snapshot_time": _now(),
                                "availability_status": availability_status,
                                "injury_type": injury_type,
                                "injury_body_part": "",
                                "is_suspended": False,
                                "suspension_reason": "",
                                "expected_return_date": None,
                                "source_name": "api-football",
                                "source_url": "",
                                "source_confidence": 0.85,
                                "recent_minutes_share": 0.0,
                                "team_market_value_share": 0.0,
                                "position_importance_score": pos_imp,
                                "replacement_quality_score": 0.5,
                                "absence_impact_score": pos_imp * 85.0,  # rough proxy
                                "raw_json": inj,
                            }

                            if not dry_run and player_id:
                                store_player_availability_snapshot(conn, snapshot)
                                injuries_collected += 1

                        except Exception as e:
                            print(f"[collect_injury] error processing injury: {e}")
                            errors += 1
                            continue

                except Exception as e:
                    print(f"[collect_injury] error for league {comp_name}: {e}")
                    errors += 1
                    continue

    finally:
        client.close()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "leagues_processed": leagues_processed,
        "injuries_collected": injuries_collected,
        "players_created": players_created,
        "errors": errors,
        "api_calls_used": client.call_count_today,
    }


def run(dry_run: bool = False, season: int | None = None) -> dict[str, Any]:
    """Run injury collection and persist its multi-agent execution record."""
    run_id = start_tracked_job(
        "injury_collection", "feature_agent", {"dry_run": dry_run, "season": season}
    )
    try:
        result = _run_impl(dry_run=dry_run, season=season)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    season = None
    for arg in sys.argv:
        if arg.startswith("--season="):
            season = int(arg.split("=")[1])
    result = run(dry_run=dry, season=season)
    print(result)
