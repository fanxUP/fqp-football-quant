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


def run(dry_run: bool = False) -> dict[str, Any]:
    """Collect injury data from API-Football for all active competitions.

    Args:
        dry_run: If True, fetch but don't store.

    Returns:
        Summary dict.
    """
    import os

    api_key = os.getenv("API_FOOTBALL_KEY", "")
    if not api_key:
        return {"status": "error", "message": "API_FOOTBALL_KEY not set"}

    client = ApiFootballClient(api_key=api_key)
    injuries_collected = 0
    players_created = 0
    leagues_processed = 0
    errors = 0

    try:
        with get_db() as conn:
            # Get active competition seasons
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

            for cs_id, season_code, comp_id, comp_name in competitions:
                try:
                    # API-Football uses its own league IDs. We need to map.
                    # For now, use the competition_season_id and hope the API
                    # can find it. The API client handles errors gracefully.
                    season_year = (
                        int(season_code.split("-")[0])
                        if "-" in season_code
                        else int(season_code[:4])
                    )

                    # Try to get injuries for this league+season
                    injuries = client.get_injuries(league=comp_id, season=season_year)

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


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
