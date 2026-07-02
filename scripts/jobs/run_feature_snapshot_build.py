"""Feature snapshot build job — full 10-dimension pipeline.

Orchestrates: team mapping → team profiles → all enrichment dimensions →
full 49-column snapshot → storage.

Stage 3a: odds, rest days, team form, basic completeness.
Stage 3b (v2_enriched): lineup, injury, rotation, travel, weather,
  motivation, tournament incentive, full completeness.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.feature_storage import store_match_feature_snapshot, store_team_season_profile
from scripts.features.build_basic_features import (
    compute_odds_implied_probabilities,
    compute_rest_days,
    compute_team_form,
)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_team_id(conn: Any, official_name: str) -> int | None:
    """Map an official team name to internal team_id via aliases."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id FROM teams t
            JOIN team_aliases ta ON ta.team_id = t.id
            WHERE ta.alias_name = %(name)s AND ta.source_name = 'sporttery'
            LIMIT 1
            """,
            {"name": official_name},
        )
        row = cur.fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Upgraded data completeness — all 10 dimensions
# ---------------------------------------------------------------------------

_DIMENSIONS = [
    "odds",
    "team_mapping",
    "team_profile",
    "lineup",
    "injury",
    "rotation",
    "travel",
    "weather",
    "motivation",
    "tournament",
]


def compute_full_completeness(dimensions: dict[str, bool]) -> dict[str, Any]:
    """Compute data completeness across all 10 feature dimensions.

    Each dimension contributes 10% to the total score.
    """
    score = 0.0
    for dim in _DIMENSIONS:
        if dimensions.get(dim, False):
            score += 10.0

    completeness = round(score, 4)
    missing = [d for d in _DIMENSIONS if not dimensions.get(d, False)]
    uncertainty = round(100.0 - completeness, 4)

    return {
        "data_completeness_score": completeness,
        "uncertainty_score": uncertainty,
        "source_confidence_score": max(0.30, completeness / 100.0 * 0.95),
        "missing_dimensions": missing,
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


def run(match_id: int | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Build full feature snapshots for matches.

    Args:
        match_id: If provided, build for a specific match. Otherwise all active.
        dry_run: If True, compute but don't store.

    Returns:
        Summary dict with counts.
    """
    if dry_run:
        return {"status": "dry_run", "message": "feature snapshot build (dry run)"}

    snap_time = _now()
    feature_version = "v2_enriched"

    with get_db() as conn:
        # ---------------------------------------------------------------
        # 1. Get matches to process
        # ---------------------------------------------------------------
        if match_id:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM official_matches WHERE id = %s", (match_id,))
                match_ids = [row[0] for row in cur.fetchall()]
        else:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT DISTINCT m.id, m.kickoff_time FROM official_matches m
                    JOIN official_odds_snapshots os ON os.match_id = m.id
                    WHERE m.match_status = 'Selling'
                    ORDER BY m.kickoff_time
                    """
                )
                match_ids = [row[0] for row in cur.fetchall()]

        if not match_ids:
            return {"status": "ok", "snapshots_built": 0, "note": "no matches to process"}

        snapshots_built = 0
        profiles_updated = 0
        dim_stats = {d: 0 for d in _DIMENSIONS}

        for mid in match_ids:
            try:
                # ---------------------------------------------------
                # 2. Load match data
                # ---------------------------------------------------
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, home_team_name, away_team_name, league_name, kickoff_time "
                        "FROM official_matches WHERE id = %s",
                        (mid,),
                    )
                    row = cur.fetchone()
                if not row:
                    continue
                match_data = {
                    "id": row[0],
                    "home_team_name": row[1],
                    "away_team_name": row[2],
                    "league_name": row[3],
                    "kickoff_time": row[4],
                }
                kt = match_data["kickoff_time"]
                kickoff_str = kt.isoformat() if isinstance(kt, datetime) else str(kt)

                # ---------------------------------------------------
                # 3. Resolve team IDs
                # ---------------------------------------------------
                home_id = _resolve_team_id(conn, match_data["home_team_name"])
                away_id = _resolve_team_id(conn, match_data["away_team_name"])
                has_mapping = home_id is not None and away_id is not None

                # ---------------------------------------------------
                # 4. Compute team profiles
                # ---------------------------------------------------
                has_profile = False
                if has_mapping and home_id and away_id:
                    for tname, tid in [
                        (match_data["home_team_name"], home_id),
                        (match_data["away_team_name"], away_id),
                    ]:
                        form = compute_team_form(tname, kickoff_str, last_n=10, conn=conn)
                        if form["matches_played"] > 0:
                            profile = {
                                "team_id": tid,
                                "competition_season_id": None,
                                "season_code": "WC2026",
                                **form,
                                "attack_strength_score": round(
                                    form["goals_for"] / max(1, form["matches_played"]), 2
                                ),
                                "defense_strength_score": round(
                                    form["goals_against"] / max(1, form["matches_played"]), 2
                                ),
                                "raw_json": form,
                            }
                            store_team_season_profile(conn, profile)
                            profiles_updated += 1
                            has_profile = True

                # ---------------------------------------------------
                # 5. Load odds
                # ---------------------------------------------------
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT play_type, option_code, sp_value FROM official_odds_snapshots
                        WHERE match_id = %s ORDER BY snapshot_time DESC
                        """,
                        (mid,),
                    )
                    odds_rows = cur.fetchall()
                has_odds = len(odds_rows) > 0
                odds_snaps = [
                    {"play_type": r[0], "option_code": r[1], "sp_value": float(r[2])}
                    for r in odds_rows
                ]
                probs = compute_odds_implied_probabilities(odds_snaps) if has_odds else {}

                # Basic features
                home_rest = compute_rest_days(match_data["home_team_name"], kickoff_str, conn)
                away_rest = compute_rest_days(match_data["away_team_name"], kickoff_str, conn)
                rest_diff = (
                    (home_rest or 0) - (away_rest or 0)
                    if home_rest is not None and away_rest is not None
                    else None
                )

                # ---------------------------------------------------
                # 6. [NEW] Lineup features
                # ---------------------------------------------------
                lineup = {}
                has_lineup = False
                try:
                    from scripts.features.build_lineup_strength import build_lineup_features

                    lineup = build_lineup_features(conn, mid, home_id, away_id)
                    has_lineup = lineup.get("has_lineup_data", False)
                except Exception as e:
                    print(f"[snapshot] lineup error match {mid}: {e}")

                # ---------------------------------------------------
                # 7. [NEW] Injury features
                # ---------------------------------------------------
                injury = {}
                has_injury = False
                try:
                    from scripts.features.build_injury_impact import build_injury_features

                    injury = build_injury_features(conn, mid, home_id, away_id)
                    has_injury = injury.get("has_injury_data", False)
                except Exception as e:
                    print(f"[snapshot] injury error match {mid}: {e}")

                # ---------------------------------------------------
                # 8. [NEW] Travel features
                # ---------------------------------------------------
                travel = {}
                has_travel = False
                try:
                    from scripts.features.build_travel_features import build_travel_features

                    travel = build_travel_features(
                        conn,
                        mid,
                        home_id,
                        away_id,
                        match_stadium_id=None,
                        kickoff_time=kt,
                    )
                    has_travel = travel.get("has_travel_data", False)
                except Exception as e:
                    print(f"[snapshot] travel error match {mid}: {e}")

                # ---------------------------------------------------
                # 9. [NEW] Weather features
                # ---------------------------------------------------
                weather = {}
                has_weather = False
                try:
                    from scripts.features.build_weather_features import build_weather_for_match

                    weather_result = build_weather_for_match(
                        conn,
                        mid,
                        kt,
                        stadium_id=travel.get("stadium_id"),
                        client=None,
                    )
                    if weather_result:
                        weather = weather_result
                        has_weather = weather_result.get("has_weather", False)
                except Exception as e:
                    print(f"[snapshot] weather error match {mid}: {e}")

                # ---------------------------------------------------
                # 10. [NEW] Motivation features
                # ---------------------------------------------------
                motivation = {}
                has_motivation = False
                try:
                    from scripts.features.build_motivation_score import build_motivation_features

                    motivation = build_motivation_features(
                        conn,
                        mid,
                        home_id,
                        away_id,
                        competition_season_id=None,
                    )
                    has_motivation = motivation.get("has_motivation_data", False)
                except Exception as e:
                    print(f"[snapshot] motivation error match {mid}: {e}")

                # ---------------------------------------------------
                # 11. [NEW] Tournament incentive features
                # ---------------------------------------------------
                tournament = {}
                has_tournament = False
                try:
                    from scripts.features.build_tournament_incentive import (
                        build_tournament_incentive_features,
                    )

                    tournament = build_tournament_incentive_features(
                        conn,
                        mid,
                        home_id,
                        away_id,
                        is_cup=False,
                    )
                    has_tournament = tournament.get("has_tournament_incentive_data", False)
                except Exception as e:
                    print(f"[snapshot] tournament error match {mid}: {e}")

                # ---------------------------------------------------
                # 12. Compute upgraded completeness
                # ---------------------------------------------------
                dims = {
                    "odds": has_odds,
                    "team_mapping": has_mapping,
                    "team_profile": has_profile,
                    "lineup": has_lineup,
                    "injury": has_injury,
                    "rotation": has_lineup,  # rotation comes from lineup analysis
                    "travel": has_travel,
                    "weather": has_weather,
                    "motivation": has_motivation,
                    "tournament": has_tournament,
                }
                completeness = compute_full_completeness(dims)
                for d in _DIMENSIONS:
                    if dims[d]:
                        dim_stats[d] += 1

                # ---------------------------------------------------
                # 13. Assemble full 49-column snapshot
                # ---------------------------------------------------
                snapshot = {
                    "match_id": mid,
                    "snapshot_time": snap_time,
                    "feature_version": feature_version,
                    "home_team_id": home_id,
                    "away_team_id": away_id,
                    "competition_season_id": None,
                    # Team strength (basic + profiles)
                    "home_team_market_value": probs.get("home_win_prob"),
                    "away_team_market_value": probs.get("away_win_prob"),
                    "team_market_value_ratio": (
                        round(probs["home_win_prob"] / probs["away_win_prob"], 4)
                        if probs.get("home_win_prob")
                        and probs.get("away_win_prob")
                        and probs["away_win_prob"] > 0
                        else None
                    ),
                    "home_attack_strength_score": probs.get("home_win_prob"),
                    "away_attack_strength_score": probs.get("away_win_prob"),
                    "home_defense_strength_score": probs.get("home_draw_prob"),
                    "away_defense_strength_score": probs.get("away_draw_prob"),
                    # Lineup (NEW)
                    "home_lineup_confirmed": lineup.get("home_lineup_confirmed"),
                    "away_lineup_confirmed": lineup.get("away_lineup_confirmed"),
                    "home_starting_11_value": lineup.get("home_starting_11_value"),
                    "away_starting_11_value": lineup.get("away_starting_11_value"),
                    "starting_11_value_diff": lineup.get("starting_11_value_diff"),
                    "home_lineup_strength_score": lineup.get("home_lineup_strength_score"),
                    "away_lineup_strength_score": lineup.get("away_lineup_strength_score"),
                    "lineup_strength_diff": lineup.get("lineup_strength_diff"),
                    # Injury (NEW)
                    "home_absence_impact_score": injury.get("home_absence_impact_score"),
                    "away_absence_impact_score": injury.get("away_absence_impact_score"),
                    "absence_impact_diff": injury.get("absence_impact_diff"),
                    "home_key_absence_count": injury.get("home_key_absence_count"),
                    "away_key_absence_count": injury.get("away_key_absence_count"),
                    # Rotation (NEW — from lineup)
                    "home_rotation_risk_score": lineup.get("home_rotation_risk_score"),
                    "away_rotation_risk_score": lineup.get("away_rotation_risk_score"),
                    "rotation_risk_diff": lineup.get("rotation_risk_diff"),
                    # Rest / schedule (existing)
                    "home_rest_days": home_rest,
                    "away_rest_days": away_rest,
                    "rest_days_diff": rest_diff,
                    # Travel (NEW)
                    "stadium_id": travel.get("stadium_id"),
                    "away_travel_distance_km": travel.get("away_travel_distance_km"),
                    "timezone_diff": travel.get("timezone_diff"),
                    "altitude_m": travel.get("altitude_m"),
                    "away_travel_fatigue_score": travel.get("away_travel_fatigue_score"),
                    # Weather (NEW)
                    "temperature_2m": weather.get("temperature_2m"),
                    "precipitation": weather.get("precipitation"),
                    "wind_speed_10m": weather.get("wind_speed_10m"),
                    "weather_impact_score": weather.get("weather_impact_score"),
                    "goal_expectation_weather_adjustment": weather.get(
                        "goal_expectation_weather_adjustment"
                    ),
                    # Motivation (NEW)
                    "home_motivation_score": motivation.get("home_motivation_score"),
                    "away_motivation_score": motivation.get("away_motivation_score"),
                    "motivation_diff": motivation.get("motivation_diff"),
                    "home_must_win": motivation.get("home_must_win"),
                    "away_must_win": motivation.get("away_must_win"),
                    "home_draw_enough": motivation.get("home_draw_enough"),
                    "away_draw_enough": motivation.get("away_draw_enough"),
                    # Tournament incentive (NEW)
                    "home_avoid_strong_opponent_score": tournament.get(
                        "home_avoid_strong_opponent_score"
                    ),
                    "away_avoid_strong_opponent_score": tournament.get(
                        "away_avoid_strong_opponent_score"
                    ),
                    "home_tanking_risk_score": tournament.get("home_tanking_risk_score"),
                    "away_tanking_risk_score": tournament.get("away_tanking_risk_score"),
                    "tournament_incentive_risk_score": tournament.get(
                        "tournament_incentive_risk_score"
                    ),
                    # Data quality
                    "data_completeness_score": completeness["data_completeness_score"],
                    "source_confidence_score": completeness["source_confidence_score"],
                    "uncertainty_score": completeness["uncertainty_score"],
                    # Metadata
                    "raw_feature_refs": {
                        "feature_version": feature_version,
                        "dimensions": dims,
                        "odds_implied": probs,
                        "source": "sporttery.cn",
                        "enrichment_sources": [
                            "api-football" if (has_injury or has_lineup) else None,
                            "open-meteo" if has_weather else None,
                            "football-data.org" if has_profile else None,
                        ],
                    },
                }

                # ---------------------------------------------------
                # 14. Store
                # ---------------------------------------------------
                snap_id = store_match_feature_snapshot(conn, snapshot)
                if snap_id:
                    snapshots_built += 1

            except Exception as e:
                print(f"[feature_snapshot_build] error on match {mid}: {e}")
                continue

    return {
        "status": "ok",
        "feature_version": feature_version,
        "snapshots_built": snapshots_built,
        "profiles_updated": profiles_updated,
        "matches_processed": len(match_ids),
        "dimensions_coverage": {d: f"{dim_stats.get(d, 0)}/{len(match_ids)}" for d in _DIMENSIONS},
    }


if __name__ == "__main__":
    import sys

    mid = int(sys.argv[1]) if len(sys.argv) > 1 else None
    dry = "--dry-run" in sys.argv
    result = run(match_id=mid, dry_run=dry)
    print(result)
