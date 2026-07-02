"""Lineup data collection job.

Pre-match job (10:00, 14:00) using ApiFootballClient.
Fetches lineups for matches within 24h and stores in
match_lineup_snapshots + match_lineup_players.

Rate limit: ~5-10 API calls/run of 100 daily limit (free tier).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.api_football_client import ApiFootballClient
from scripts.feature_storage import (
    get_player_by_code,
    store_match_lineup_player,
    store_match_lineup_snapshot,
    store_player,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_or_create_player(conn: Any, player_data: dict) -> int | None:
    """Find or create player, return player_id."""
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
            "birth_date": (
                player_data.get("birth", {}).get("date")
                if isinstance(player_data.get("birth"), dict)
                else None
            ),
            "nationality": player_data.get("nationality", ""),
            "primary_position": player_data.get("position", ""),
            "secondary_positions": [],
            "preferred_foot": "",
            "height_cm": (
                float(player_data.get("height", "").replace(" cm", ""))
                if player_data.get("height")
                else None
            ),
        },
    )


def _resolve_team_id(conn: Any, team_name: str) -> int | None:
    """Map team name to internal team_id via aliases."""
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


def _process_lineup(
    conn: Any,
    match_id: int,
    team_data: dict,
    team_id: int,
    snapshot_time: str,
) -> int | None:
    """Process a single team's lineup from API-Football fixture data.

    Stores the lineup snapshot and its players.

    Returns lineup_snapshot_id or None.
    """
    # Extract formation info
    formation = team_data.get("formation", "")
    start_xi = team_data.get("startXI", [])
    substitutes = team_data.get("substitutes", [])

    # Compute aggregate stats
    starting_values: list[float] = []
    key_count = 0
    player_records = []

    for p in start_xi:
        player_info = p.get("player", {})
        player_id = _get_or_create_player(conn, player_info)
        if not player_id:
            continue

        pos = p.get("player", {}).get("position", "")
        mv = None  # market value not directly in fixtures

        player_records.append(
            {
                "player_id": player_id,
                "is_starting": True,
                "is_substitute": False,
                "position": pos,
                "tactical_role": "",
                "market_value": mv,
                "recent_minutes": None,
                "key_player_score": 50.0 if pos in ("G", "D", "M", "F") else 30.0,
            }
        )

        if mv:
            starting_values.append(mv)

        # Count key players (rough heuristic)
        if pos in ("G", "D"):
            key_count += 1

    for p in substitutes:
        player_info = p.get("player", {})
        player_id = _get_or_create_player(conn, player_info)
        if not player_id:
            continue

        player_records.append(
            {
                "player_id": player_id,
                "is_starting": False,
                "is_substitute": True,
                "position": p.get("player", {}).get("position", ""),
                "tactical_role": "",
                "market_value": None,
                "recent_minutes": None,
                "key_player_score": 20.0,
            }
        )

    total_value = sum(starting_values) if starting_values else None

    # Store lineup snapshot
    lineup_snapshot = {
        "match_id": match_id,
        "team_id": team_id,
        "snapshot_time": snapshot_time,
        "lineup_type": "predicted",
        "source_name": "api-football",
        "source_confidence": 0.85,
        "formation": formation,
        "formation_changed": False,
        "goalkeeper_changed": False,
        "center_back_pair_changed": False,
        "starting_11_market_value": total_value,
        "starting_11_avg_age": None,
        "starting_11_recent_minutes": None,
        "starting_11_key_player_count": key_count,
        "bench_market_value": None,
        "bench_strength_score": 50.0,
        "lineup_strength_score": (
            min(100.0, (total_value or 0) / 10_000_000 * 50) if total_value else 50.0
        ),
        "rotation_risk_score": 30.0,
        "lineup_uncertainty_score": 50.0,  # predicted lineups are uncertain
        "raw_json": team_data,
    }

    lineup_id = store_match_lineup_snapshot(conn, lineup_snapshot)
    if not lineup_id:
        return None

    # Store players
    for pr in player_records:
        pr["lineup_snapshot_id"] = lineup_id
        store_match_lineup_player(conn, pr)

    return lineup_id


def run(dry_run: bool = False) -> dict[str, Any]:
    """Collect lineup data from API-Football for upcoming matches.

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
    lineups_collected = 0
    matches_processed = 0
    errors = 0

    try:
        with get_db() as conn:
            # Get matches within the next 24 hours
            now = datetime.now()
            cutoff = now + timedelta(hours=24)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, home_team_name, away_team_name, kickoff_time
                    FROM official_matches
                    WHERE match_status = 'Selling'
                      AND kickoff_time BETWEEN %(now)s AND %(cutoff)s
                    ORDER BY kickoff_time
                    LIMIT 20
                    """,
                    {"now": now, "cutoff": cutoff},
                )
                matches = [
                    {
                        "id": r[0],
                        "home_team_name": r[1],
                        "away_team_name": r[2],
                        "kickoff_time": r[3],
                    }
                    for r in cur.fetchall()
                ]

            if not matches:
                return {"status": "ok", "note": "no upcoming matches in next 24h"}

            snap_time = _now()

            for match in matches:
                try:
                    home_id = _resolve_team_id(conn, match["home_team_name"])
                    away_id = _resolve_team_id(conn, match["away_team_name"])

                    if not home_id or not away_id:
                        print(
                            f"[collect_lineup] cannot resolve teams for match {match['id']}: "
                            f"{match['home_team_name']} vs {match['away_team_name']}"
                        )
                        continue

                    # Try to get lineups from API
                    # Use date-based search since we may not have API-Football fixture IDs
                    match_date = (
                        match["kickoff_time"].strftime("%Y-%m-%d")
                        if isinstance(match["kickoff_time"], datetime)
                        else str(match["kickoff_time"])[:10]
                    )

                    fixtures = client.get_fixtures(date=match_date)

                    if not fixtures:
                        matches_processed += 1
                        continue

                    # Find the fixture matching our teams by name
                    for fix in fixtures:
                        fix_home = fix.get("teams", {}).get("home", {}).get("name", "")
                        fix_away = fix.get("teams", {}).get("away", {}).get("name", "")

                        if (
                            fix_home == match["home_team_name"]
                            and fix_away == match["away_team_name"]
                        ):
                            if not dry_run:
                                # Extract lineups from fixture
                                lineups = fix.get("lineups", [])
                                for team_lineup in lineups:
                                    team_name = team_lineup.get("team", {}).get("name", "")
                                    team_id = (
                                        home_id
                                        if team_name == match["home_team_name"]
                                        else away_id
                                        if team_name == match["away_team_name"]
                                        else None
                                    )
                                    if team_id:
                                        lid = _process_lineup(
                                            conn, match["id"], team_lineup, team_id, snap_time
                                        )
                                        if lid:
                                            lineups_collected += 1
                            break  # found our match

                    matches_processed += 1

                except Exception as e:
                    print(f"[collect_lineup] error for match {match['id']}: {e}")
                    errors += 1
                    continue

    finally:
        client.close()

    return {
        "status": "ok" if not dry_run else "dry_run",
        "matches_processed": matches_processed,
        "lineups_collected": lineups_collected,
        "errors": errors,
        "api_calls_used": client.call_count_today,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
