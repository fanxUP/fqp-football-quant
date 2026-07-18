"""Feature data storage layer.

CRUD for Stage 3 feature tables:
  - team_season_profiles
  - match_feature_snapshots

Follows the same psycopg2 pattern as scripts/official_storage.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# team_season_profiles
# ---------------------------------------------------------------------------


def store_team_season_profile(conn: Any, profile: dict) -> int | None:
    """Upsert one canonical team-profile snapshot."""
    competition_season_id = profile.get("competition_season_id")
    if not competition_season_id:
        return None

    params = {
        "team_id": profile["team_id"],
        "competition_season_id": competition_season_id,
        "snapshot_time": profile.get("snapshot_time", _now()),
        "attack_strength_score": profile.get("attack_strength_score"),
        "defense_strength_score": profile.get("defense_strength_score"),
        "data_source": profile.get("data_source", "computed_form"),
        "data_confidence": profile.get("data_confidence"),
        "raw_json": json.dumps(profile.get("raw_json", {}), ensure_ascii=False),
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO team_season_profiles (
                team_id, competition_season_id, snapshot_time,
                attack_strength_score, defense_strength_score,
                data_source, data_confidence, raw_json, created_at, updated_at
            ) VALUES (
                %(team_id)s, %(competition_season_id)s, %(snapshot_time)s,
                %(attack_strength_score)s, %(defense_strength_score)s,
                %(data_source)s, %(data_confidence)s, %(raw_json)s, now(), now()
            )
            ON CONFLICT (team_id, competition_season_id, snapshot_time) DO UPDATE SET
                attack_strength_score = EXCLUDED.attack_strength_score,
                defense_strength_score = EXCLUDED.defense_strength_score,
                data_source = EXCLUDED.data_source,
                data_confidence = EXCLUDED.data_confidence,
                raw_json = EXCLUDED.raw_json,
                updated_at = now()
            RETURNING id
            """,
            params,
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# match_feature_snapshots
# ---------------------------------------------------------------------------


def store_match_feature_snapshot(conn: Any, snapshot: dict) -> int | None:
    """Insert a match feature snapshot.

    Required: match_id, snapshot_time, feature_version
    Append-only — each call creates a new row.

    Returns the snapshot id.
    """
    sql = """
        INSERT INTO match_feature_snapshots (
            match_id, snapshot_time, feature_version,
            home_team_id, away_team_id, competition_season_id,
            -- team strength
            home_team_market_value, away_team_market_value,
            team_market_value_diff, team_market_value_ratio,
            home_attack_strength_score, away_attack_strength_score,
            home_defense_strength_score, away_defense_strength_score,
            -- rest / schedule
            home_rest_days, away_rest_days, rest_days_diff,
            -- motivation
            home_motivation_score, away_motivation_score, motivation_diff,
            -- data quality
            data_completeness_score, source_confidence_score, uncertainty_score,
            raw_feature_refs, created_at
        ) VALUES (
            %(match_id)s, %(snapshot_time)s, %(feature_version)s,
            %(home_team_id)s, %(away_team_id)s, %(competition_season_id)s,
            %(home_team_market_value)s, %(away_team_market_value)s,
            %(team_market_value_diff)s, %(team_market_value_ratio)s,
            %(home_attack_strength_score)s, %(away_attack_strength_score)s,
            %(home_defense_strength_score)s, %(away_defense_strength_score)s,
            %(home_rest_days)s, %(away_rest_days)s, %(rest_days_diff)s,
            %(home_motivation_score)s, %(away_motivation_score)s, %(motivation_diff)s,
            %(data_completeness_score)s, %(source_confidence_score)s, %(uncertainty_score)s,
            %(raw_feature_refs)s, now()
        )
        RETURNING id
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            {
                "match_id": snapshot["match_id"],
                "snapshot_time": snapshot.get("snapshot_time", _now()),
                "feature_version": snapshot.get("feature_version", "v1_basic"),
                "home_team_id": snapshot.get("home_team_id"),
                "away_team_id": snapshot.get("away_team_id"),
                "competition_season_id": snapshot.get("competition_season_id"),
                "home_team_market_value": snapshot.get("home_team_market_value"),
                "away_team_market_value": snapshot.get("away_team_market_value"),
                "team_market_value_diff": snapshot.get("team_market_value_diff"),
                "team_market_value_ratio": snapshot.get("team_market_value_ratio"),
                "home_attack_strength_score": snapshot.get("home_attack_strength_score"),
                "away_attack_strength_score": snapshot.get("away_attack_strength_score"),
                "home_defense_strength_score": snapshot.get("home_defense_strength_score"),
                "away_defense_strength_score": snapshot.get("away_defense_strength_score"),
                "home_rest_days": snapshot.get("home_rest_days"),
                "away_rest_days": snapshot.get("away_rest_days"),
                "rest_days_diff": snapshot.get("rest_days_diff"),
                "home_motivation_score": snapshot.get("home_motivation_score"),
                "away_motivation_score": snapshot.get("away_motivation_score"),
                "motivation_diff": snapshot.get("motivation_diff"),
                "data_completeness_score": snapshot.get("data_completeness_score"),
                "source_confidence_score": snapshot.get("source_confidence_score"),
                "uncertainty_score": snapshot.get("uncertainty_score"),
                "raw_feature_refs": json.dumps(
                    snapshot.get("raw_feature_refs", {}), ensure_ascii=False
                ),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# match_weather_snapshots
# ---------------------------------------------------------------------------


def store_match_weather_snapshot(conn: Any, snapshot: dict) -> int | None:
    """Insert or update a weather snapshot for a match.

    Required: match_id, snapshot_time, forecast_for_time
    Upsert by (match_id) — only the latest weather matters per match.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM match_weather_snapshots WHERE match_id = %(match_id)s",
            {"match_id": snapshot["match_id"]},
        )
        row = cur.fetchone()

        common = {
            "match_id": snapshot["match_id"],
            "stadium_id": snapshot.get("stadium_id"),
            "snapshot_time": snapshot.get("snapshot_time", _now()),
            "forecast_for_time": snapshot.get("forecast_for_time", _now()),
            "temperature_2m": snapshot.get("temperature_2m"),
            "apparent_temperature": snapshot.get("apparent_temperature"),
            "relative_humidity_2m": snapshot.get("relative_humidity_2m"),
            "precipitation": snapshot.get("precipitation"),
            "rain": snapshot.get("rain"),
            "snowfall": snapshot.get("snowfall"),
            "wind_speed_10m": snapshot.get("wind_speed_10m"),
            "wind_gusts_10m": snapshot.get("wind_gusts_10m"),
            "surface_pressure": snapshot.get("surface_pressure"),
            "cloud_cover": snapshot.get("cloud_cover"),
            "weather_code": snapshot.get("weather_code", ""),
            "weather_impact_score": snapshot.get("weather_impact_score"),
            "tempo_penalty_score": snapshot.get("tempo_penalty_score"),
            "goal_expectation_adjustment": snapshot.get("goal_expectation_adjustment"),
            "uncertainty_adjustment": snapshot.get("uncertainty_adjustment"),
            "source_name": snapshot.get("source_name", "open-meteo"),
            "source_confidence": snapshot.get("source_confidence", 0.85),
            "raw_json": json.dumps(snapshot.get("raw_json", {}), ensure_ascii=False),
        }

        if row:
            cur.execute(
                """
                UPDATE match_weather_snapshots SET
                    stadium_id = %(stadium_id)s,
                    snapshot_time = %(snapshot_time)s,
                    forecast_for_time = %(forecast_for_time)s,
                    temperature_2m = %(temperature_2m)s,
                    apparent_temperature = %(apparent_temperature)s,
                    relative_humidity_2m = %(relative_humidity_2m)s,
                    precipitation = %(precipitation)s,
                    rain = %(rain)s,
                    snowfall = %(snowfall)s,
                    wind_speed_10m = %(wind_speed_10m)s,
                    wind_gusts_10m = %(wind_gusts_10m)s,
                    surface_pressure = %(surface_pressure)s,
                    cloud_cover = %(cloud_cover)s,
                    weather_code = %(weather_code)s,
                    weather_impact_score = %(weather_impact_score)s,
                    tempo_penalty_score = %(tempo_penalty_score)s,
                    goal_expectation_adjustment = %(goal_expectation_adjustment)s,
                    uncertainty_adjustment = %(uncertainty_adjustment)s,
                    source_name = %(source_name)s,
                    source_confidence = %(source_confidence)s,
                    raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            conn.commit()
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO match_weather_snapshots (
                    match_id, stadium_id, snapshot_time, forecast_for_time,
                    temperature_2m, apparent_temperature, relative_humidity_2m,
                    precipitation, rain, snowfall,
                    wind_speed_10m, wind_gusts_10m, surface_pressure, cloud_cover,
                    weather_code, weather_impact_score, tempo_penalty_score,
                    goal_expectation_adjustment, uncertainty_adjustment,
                    source_name, source_confidence, raw_json
                ) VALUES (
                    %(match_id)s, %(stadium_id)s, %(snapshot_time)s, %(forecast_for_time)s,
                    %(temperature_2m)s, %(apparent_temperature)s, %(relative_humidity_2m)s,
                    %(precipitation)s, %(rain)s, %(snowfall)s,
                    %(wind_speed_10m)s, %(wind_gusts_10m)s, %(surface_pressure)s, %(cloud_cover)s,
                    %(weather_code)s, %(weather_impact_score)s, %(tempo_penalty_score)s,
                    %(goal_expectation_adjustment)s, %(uncertainty_adjustment)s,
                    %(source_name)s, %(source_confidence)s, %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_weather_for_match(conn: Any, match_id: int) -> dict | None:
    """Get the latest weather snapshot for a match."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT match_id, stadium_id, snapshot_time, forecast_for_time,
                   temperature_2m, precipitation, wind_speed_10m,
                   weather_impact_score, goal_expectation_adjustment,
                   source_name, source_confidence
            FROM match_weather_snapshots
            WHERE match_id = %s
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (match_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "match_id": row[0],
        "stadium_id": row[1],
        "snapshot_time": row[2],
        "forecast_for_time": row[3],
        "temperature_2m": row[4],
        "precipitation": row[5],
        "wind_speed_10m": row[6],
        "weather_impact_score": row[7],
        "goal_expectation_adjustment": row[8],
        "source_name": row[9],
        "source_confidence": row[10],
    }


# ---------------------------------------------------------------------------
# players
# ---------------------------------------------------------------------------


def store_player(conn: Any, player: dict) -> int | None:
    """Insert or update a player. Upsert by api_player_id (stored in player_code).

    Required: player_code (unique external ID), player_name_en or player_name_cn.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM players WHERE player_code = %(code)s",
            {"code": player["player_code"]},
        )
        row = cur.fetchone()
        common = {
            "player_code": player["player_code"],
            "player_name_cn": player.get("player_name_cn", ""),
            "player_name_en": player.get("player_name_en", ""),
            "birth_date": player.get("birth_date"),
            "nationality": player.get("nationality", ""),
            "primary_position": player.get("primary_position", ""),
            "secondary_positions": json.dumps(
                player.get("secondary_positions", []), ensure_ascii=False
            ),
            "preferred_foot": player.get("preferred_foot", ""),
            "height_cm": player.get("height_cm"),
        }
        if row:
            cur.execute(
                """
                UPDATE players SET
                    player_name_cn = %(player_name_cn)s,
                    player_name_en = %(player_name_en)s,
                    birth_date = %(birth_date)s,
                    nationality = %(nationality)s,
                    primary_position = %(primary_position)s,
                    secondary_positions = %(secondary_positions)s,
                    preferred_foot = %(preferred_foot)s,
                    height_cm = %(height_cm)s,
                    updated_at = now()
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO players (
                    player_code, player_name_cn, player_name_en,
                    birth_date, nationality, primary_position, secondary_positions,
                    preferred_foot, height_cm
                ) VALUES (
                    %(player_code)s, %(player_name_cn)s, %(player_name_en)s,
                    %(birth_date)s, %(nationality)s, %(primary_position)s, %(secondary_positions)s,
                    %(preferred_foot)s, %(height_cm)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_player_by_code(conn: Any, player_code: str) -> dict | None:
    """Look up a player by their external player_code."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, player_code, player_name_en, primary_position FROM players WHERE player_code = %s",
            (player_code,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "player_code": row[1],
        "player_name_en": row[2],
        "primary_position": row[3],
    }


# ---------------------------------------------------------------------------
# player_season_profiles
# ---------------------------------------------------------------------------


def store_player_season_profile(conn: Any, profile: dict) -> int | None:
    """Upsert a player's season profile. Key: (player_id, team_id, competition_season_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM player_season_profiles
            WHERE player_id = %(player_id)s AND team_id = %(team_id)s
              AND competition_season_id = %(competition_season_id)s
            """,
            {
                "player_id": profile["player_id"],
                "team_id": profile["team_id"],
                "competition_season_id": profile["competition_season_id"],
            },
        )
        row = cur.fetchone()
        common = {
            "player_id": profile["player_id"],
            "team_id": profile["team_id"],
            "competition_season_id": profile["competition_season_id"],
            "shirt_number": profile.get("shirt_number", ""),
            "position": profile.get("position", ""),
            "role_type": profile.get("role_type", ""),
            "market_value": profile.get("market_value"),
            "market_value_currency": profile.get("market_value_currency", "EUR"),
            "market_value_rank_in_team": profile.get("market_value_rank_in_team"),
            "appearances": profile.get("appearances"),
            "starts": profile.get("starts"),
            "minutes_played": profile.get("minutes_played"),
            "goals": profile.get("goals"),
            "assists": profile.get("assists"),
            "yellow_cards": profile.get("yellow_cards"),
            "red_cards": profile.get("red_cards"),
            "recent_5_starts": profile.get("recent_5_starts"),
            "recent_5_minutes": profile.get("recent_5_minutes"),
            "recent_10_starts": profile.get("recent_10_starts"),
            "recent_10_minutes": profile.get("recent_10_minutes"),
            "is_key_player": profile.get("is_key_player", False),
            "key_player_score": profile.get("key_player_score"),
            "starter_probability": profile.get("starter_probability"),
            "contract_until": profile.get("contract_until"),
        }
        if row:
            cur.execute(
                """
                UPDATE player_season_profiles SET
                    shirt_number = %(shirt_number)s, position = %(position)s,
                    role_type = %(role_type)s, market_value = %(market_value)s,
                    market_value_currency = %(market_value_currency)s,
                    market_value_rank_in_team = %(market_value_rank_in_team)s,
                    appearances = %(appearances)s, starts = %(starts)s,
                    minutes_played = %(minutes_played)s, goals = %(goals)s,
                    assists = %(assists)s, yellow_cards = %(yellow_cards)s,
                    red_cards = %(red_cards)s, recent_5_starts = %(recent_5_starts)s,
                    recent_5_minutes = %(recent_5_minutes)s, recent_10_starts = %(recent_10_starts)s,
                    recent_10_minutes = %(recent_10_minutes)s, is_key_player = %(is_key_player)s,
                    key_player_score = %(key_player_score)s,
                    starter_probability = %(starter_probability)s,
                    contract_until = %(contract_until)s, updated_at = now()
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO player_season_profiles (
                    player_id, team_id, competition_season_id,
                    shirt_number, position, role_type, market_value, market_value_currency,
                    market_value_rank_in_team, appearances, starts, minutes_played,
                    goals, assists, yellow_cards, red_cards,
                    recent_5_starts, recent_5_minutes, recent_10_starts, recent_10_minutes,
                    is_key_player, key_player_score, starter_probability, contract_until
                ) VALUES (
                    %(player_id)s, %(team_id)s, %(competition_season_id)s,
                    %(shirt_number)s, %(position)s, %(role_type)s, %(market_value)s, %(market_value_currency)s,
                    %(market_value_rank_in_team)s, %(appearances)s, %(starts)s, %(minutes_played)s,
                    %(goals)s, %(assists)s, %(yellow_cards)s, %(red_cards)s,
                    %(recent_5_starts)s, %(recent_5_minutes)s, %(recent_10_starts)s, %(recent_10_minutes)s,
                    %(is_key_player)s, %(key_player_score)s, %(starter_probability)s, %(contract_until)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# team_squad_snapshots
# ---------------------------------------------------------------------------


def store_team_squad_snapshot(conn: Any, snapshot: dict) -> int | None:
    """Insert a team squad snapshot (append-only — each call is a new snapshot)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO team_squad_snapshots (
                team_id, competition_season_id, snapshot_time,
                available_players_count, injured_players_count,
                suspended_players_count, doubtful_players_count,
                available_market_value, unavailable_market_value, unavailable_value_ratio,
                key_absence_count, goalkeeper_available,
                center_back_available_count, striker_available_count,
                squad_health_score, squad_depth_score, data_confidence, raw_json
            ) VALUES (
                %(team_id)s, %(competition_season_id)s, %(snapshot_time)s,
                %(available_players_count)s, %(injured_players_count)s,
                %(suspended_players_count)s, %(doubtful_players_count)s,
                %(available_market_value)s, %(unavailable_market_value)s, %(unavailable_value_ratio)s,
                %(key_absence_count)s, %(goalkeeper_available)s,
                %(center_back_available_count)s, %(striker_available_count)s,
                %(squad_health_score)s, %(squad_depth_score)s, %(data_confidence)s,
                %(raw_json)s
            )
            RETURNING id
            """,
            {
                "team_id": snapshot["team_id"],
                "competition_season_id": snapshot.get("competition_season_id"),
                "snapshot_time": snapshot.get("snapshot_time", _now()),
                "available_players_count": snapshot.get("available_players_count"),
                "injured_players_count": snapshot.get("injured_players_count"),
                "suspended_players_count": snapshot.get("suspended_players_count"),
                "doubtful_players_count": snapshot.get("doubtful_players_count"),
                "available_market_value": snapshot.get("available_market_value"),
                "unavailable_market_value": snapshot.get("unavailable_market_value"),
                "unavailable_value_ratio": snapshot.get("unavailable_value_ratio"),
                "key_absence_count": snapshot.get("key_absence_count"),
                "goalkeeper_available": snapshot.get("goalkeeper_available"),
                "center_back_available_count": snapshot.get("center_back_available_count"),
                "striker_available_count": snapshot.get("striker_available_count"),
                "squad_health_score": snapshot.get("squad_health_score"),
                "squad_depth_score": snapshot.get("squad_depth_score"),
                "data_confidence": snapshot.get("data_confidence", 0.85),
                "raw_json": json.dumps(snapshot.get("raw_json", {}), ensure_ascii=False),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# match_lineup_snapshots + match_lineup_players
# ---------------------------------------------------------------------------


def store_match_lineup_snapshot(conn: Any, lineup: dict) -> int | None:
    """Upsert a match lineup snapshot by (match_id, team_id, snapshot_time)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM match_lineup_snapshots
            WHERE match_id = %(match_id)s AND team_id = %(team_id)s
            ORDER BY snapshot_time DESC LIMIT 1
            """,
            {"match_id": lineup["match_id"], "team_id": lineup["team_id"]},
        )
        row = cur.fetchone()
        common = {
            "match_id": lineup["match_id"],
            "team_id": lineup["team_id"],
            "snapshot_time": lineup.get("snapshot_time", _now()),
            "lineup_type": lineup.get("lineup_type", "predicted"),
            "source_name": lineup.get("source_name", "api-football"),
            "source_confidence": lineup.get("source_confidence", 0.85),
            "formation": lineup.get("formation", ""),
            "formation_changed": lineup.get("formation_changed", False),
            "goalkeeper_changed": lineup.get("goalkeeper_changed", False),
            "center_back_pair_changed": lineup.get("center_back_pair_changed", False),
            "starting_11_market_value": lineup.get("starting_11_market_value"),
            "starting_11_avg_age": lineup.get("starting_11_avg_age"),
            "starting_11_recent_minutes": lineup.get("starting_11_recent_minutes"),
            "starting_11_key_player_count": lineup.get("starting_11_key_player_count"),
            "bench_market_value": lineup.get("bench_market_value"),
            "bench_strength_score": lineup.get("bench_strength_score"),
            "lineup_strength_score": lineup.get("lineup_strength_score"),
            "rotation_risk_score": lineup.get("rotation_risk_score"),
            "lineup_uncertainty_score": lineup.get("lineup_uncertainty_score"),
            "raw_json": json.dumps(lineup.get("raw_json", {}), ensure_ascii=False),
        }
        if row:
            cur.execute(
                """
                UPDATE match_lineup_snapshots SET
                    snapshot_time = %(snapshot_time)s, lineup_type = %(lineup_type)s,
                    source_name = %(source_name)s, source_confidence = %(source_confidence)s,
                    formation = %(formation)s, formation_changed = %(formation_changed)s,
                    goalkeeper_changed = %(goalkeeper_changed)s,
                    center_back_pair_changed = %(center_back_pair_changed)s,
                    starting_11_market_value = %(starting_11_market_value)s,
                    starting_11_avg_age = %(starting_11_avg_age)s,
                    starting_11_recent_minutes = %(starting_11_recent_minutes)s,
                    starting_11_key_player_count = %(starting_11_key_player_count)s,
                    bench_market_value = %(bench_market_value)s,
                    bench_strength_score = %(bench_strength_score)s,
                    lineup_strength_score = %(lineup_strength_score)s,
                    rotation_risk_score = %(rotation_risk_score)s,
                    lineup_uncertainty_score = %(lineup_uncertainty_score)s,
                    raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            lineup_id = row[0]
        else:
            cur.execute(
                """
                INSERT INTO match_lineup_snapshots (
                    match_id, team_id, snapshot_time, lineup_type,
                    source_name, source_confidence, formation,
                    formation_changed, goalkeeper_changed, center_back_pair_changed,
                    starting_11_market_value, starting_11_avg_age,
                    starting_11_recent_minutes, starting_11_key_player_count,
                    bench_market_value, bench_strength_score,
                    lineup_strength_score, rotation_risk_score, lineup_uncertainty_score,
                    raw_json
                ) VALUES (
                    %(match_id)s, %(team_id)s, %(snapshot_time)s, %(lineup_type)s,
                    %(source_name)s, %(source_confidence)s, %(formation)s,
                    %(formation_changed)s, %(goalkeeper_changed)s, %(center_back_pair_changed)s,
                    %(starting_11_market_value)s, %(starting_11_avg_age)s,
                    %(starting_11_recent_minutes)s, %(starting_11_key_player_count)s,
                    %(bench_market_value)s, %(bench_strength_score)s,
                    %(lineup_strength_score)s, %(rotation_risk_score)s, %(lineup_uncertainty_score)s,
                    %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
            lineup_id = row[0] if row else None
    conn.commit()
    return lineup_id


def store_match_lineup_player(conn: Any, lp: dict) -> int | None:
    """Insert a player in a lineup snapshot.

    Required: lineup_snapshot_id, player_id.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO match_lineup_players (
                lineup_snapshot_id, player_id, is_starting, is_substitute,
                position, tactical_role, market_value, recent_minutes, key_player_score
            ) VALUES (
                %(lineup_snapshot_id)s, %(player_id)s, %(is_starting)s, %(is_substitute)s,
                %(position)s, %(tactical_role)s, %(market_value)s, %(recent_minutes)s, %(key_player_score)s
            )
            RETURNING id
            """,
            {
                "lineup_snapshot_id": lp["lineup_snapshot_id"],
                "player_id": lp["player_id"],
                "is_starting": lp.get("is_starting", False),
                "is_substitute": lp.get("is_substitute", False),
                "position": lp.get("position", ""),
                "tactical_role": lp.get("tactical_role", ""),
                "market_value": lp.get("market_value"),
                "recent_minutes": lp.get("recent_minutes"),
                "key_player_score": lp.get("key_player_score"),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_lineup_for_match(conn: Any, match_id: int, team_id: int) -> dict | None:
    """Get the latest lineup snapshot for a match+team."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, formation, lineup_strength_score, rotation_risk_score,
                   starting_11_market_value, starting_11_key_player_count,
                   lineup_type, lineup_uncertainty_score
            FROM match_lineup_snapshots
            WHERE match_id = %s AND team_id = %s
            ORDER BY snapshot_time DESC LIMIT 1
            """,
            (match_id, team_id),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "formation": row[1],
        "lineup_strength_score": row[2],
        "rotation_risk_score": row[3],
        "starting_11_market_value": row[4],
        "starting_11_key_player_count": row[5],
        "lineup_type": row[6],
        "lineup_uncertainty_score": row[7],
    }


# ---------------------------------------------------------------------------
# player_availability_snapshots (injury/suspension)
# ---------------------------------------------------------------------------


def store_player_availability_snapshot(conn: Any, snap: dict) -> int | None:
    """Upsert a player availability snapshot.

    Upsert by (player_id, official_match_id) when the source observation is
    match-specific. Historical league snapshots retain the legacy player rule.
    """
    raw_json = snap.get("raw_json", {})
    official_match_id = (
        raw_json.get("official_match_id") if isinstance(raw_json, dict) else None
    )
    with conn.cursor() as cur:
        if official_match_id:
            cur.execute(
                """
                SELECT id FROM player_availability_snapshots
                WHERE player_id = %(player_id)s
                  AND raw_json->>'official_match_id' = %(official_match_id)s
                """,
                {
                    "player_id": snap["player_id"],
                    "official_match_id": str(official_match_id),
                },
            )
        else:
            cur.execute(
                """
                SELECT id FROM player_availability_snapshots
                WHERE player_id = %(player_id)s
                ORDER BY snapshot_time DESC LIMIT 1
                """,
                {"player_id": snap["player_id"]},
            )
        row = cur.fetchone()
        common = {
            "player_id": snap["player_id"],
            "team_id": snap.get("team_id"),
            "competition_season_id": snap.get("competition_season_id"),
            "snapshot_time": snap.get("snapshot_time", _now()),
            "availability_status": snap.get("availability_status", "unknown"),
            "injury_type": snap.get("injury_type", ""),
            "injury_body_part": snap.get("injury_body_part", ""),
            "is_suspended": snap.get("is_suspended", False),
            "suspension_reason": snap.get("suspension_reason", ""),
            "expected_return_date": snap.get("expected_return_date"),
            "source_name": snap.get("source_name", "api-football"),
            "source_url": snap.get("source_url", ""),
            "source_confidence": snap.get("source_confidence", 0.85),
            "recent_minutes_share": snap.get("recent_minutes_share"),
            "team_market_value_share": snap.get("team_market_value_share"),
            "position_importance_score": snap.get("position_importance_score"),
            "replacement_quality_score": snap.get("replacement_quality_score"),
            "absence_impact_score": snap.get("absence_impact_score"),
            "raw_json": json.dumps(snap.get("raw_json", {}), ensure_ascii=False),
        }
        if row:
            snapshot_id = row[0]
            cur.execute(
                """
                UPDATE player_availability_snapshots SET
                    team_id = %(team_id)s, competition_season_id = %(competition_season_id)s,
                    snapshot_time = %(snapshot_time)s, availability_status = %(availability_status)s,
                    injury_type = %(injury_type)s, injury_body_part = %(injury_body_part)s,
                    is_suspended = %(is_suspended)s, suspension_reason = %(suspension_reason)s,
                    expected_return_date = %(expected_return_date)s,
                    source_name = %(source_name)s, source_url = %(source_url)s,
                    source_confidence = %(source_confidence)s,
                    recent_minutes_share = %(recent_minutes_share)s,
                    team_market_value_share = %(team_market_value_share)s,
                    position_importance_score = %(position_importance_score)s,
                    replacement_quality_score = %(replacement_quality_score)s,
                    absence_impact_score = %(absence_impact_score)s,
                    raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": snapshot_id},
            )
        else:
            cur.execute(
                """
                INSERT INTO player_availability_snapshots (
                    player_id, team_id, competition_season_id, snapshot_time,
                    availability_status, injury_type, injury_body_part,
                    is_suspended, suspension_reason, expected_return_date,
                    source_name, source_url, source_confidence,
                    recent_minutes_share, team_market_value_share,
                    position_importance_score, replacement_quality_score,
                    absence_impact_score, raw_json
                ) VALUES (
                    %(player_id)s, %(team_id)s, %(competition_season_id)s, %(snapshot_time)s,
                    %(availability_status)s, %(injury_type)s, %(injury_body_part)s,
                    %(is_suspended)s, %(suspension_reason)s, %(expected_return_date)s,
                    %(source_name)s, %(source_url)s, %(source_confidence)s,
                    %(recent_minutes_share)s, %(team_market_value_share)s,
                    %(position_importance_score)s, %(replacement_quality_score)s,
                    %(absence_impact_score)s, %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
            snapshot_id = row[0] if row else None
    conn.commit()
    return snapshot_id


def get_injuries_for_team(
    conn: Any, team_id: int, before_match_date: str | None = None
) -> list[dict]:
    """Get latest injury/availability data for a team."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (player_id)
                player_id, team_id, availability_status, injury_type,
                injury_body_part, is_suspended, expected_return_date,
                absence_impact_score, position_importance_score,
                source_name, source_confidence
            FROM player_availability_snapshots
            WHERE team_id = %s AND availability_status IN ('injured', 'suspended', 'doubtful')
            ORDER BY player_id, snapshot_time DESC
            """,
            (team_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "player_id": r[0],
            "team_id": r[1],
            "availability_status": r[2],
            "injury_type": r[3],
            "injury_body_part": r[4],
            "is_suspended": r[5],
            "expected_return_date": r[6],
            "absence_impact_score": r[7],
            "position_importance_score": r[8],
            "source_name": r[9],
            "source_confidence": r[10],
        }
        for r in rows
    ]


def get_injuries_for_match(conn: Any, match_id: int, team_id: int) -> list[dict]:
    """读取某场比赛某队的最新球员缺阵记录。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (player_id)
                player_id, team_id, availability_status, injury_type,
                injury_body_part, is_suspended, expected_return_date,
                absence_impact_score, position_importance_score,
                source_name, source_confidence
            FROM player_availability_snapshots
            WHERE team_id = %(team_id)s
              AND raw_json->>'official_match_id' = %(match_id)s
              AND availability_status IN ('injured', 'suspended', 'doubtful')
            ORDER BY player_id, snapshot_time DESC
            """,
            {"team_id": team_id, "match_id": str(match_id)},
        )
        rows = cur.fetchall()
    return [
        {
            "player_id": row[0],
            "team_id": row[1],
            "availability_status": row[2],
            "injury_type": row[3],
            "injury_body_part": row[4],
            "is_suspended": row[5],
            "expected_return_date": row[6],
            "absence_impact_score": row[7],
            "position_importance_score": row[8],
            "source_name": row[9],
            "source_confidence": row[10],
        }
        for row in rows
    ]


def get_injury_observation_for_match(
    conn: Any, match_id: int, team_id: int
) -> dict[str, Any] | None:
    """读取比赛级伤停查询回执，包括“已查询但为零伤停”。"""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT injured_players_count, suspended_players_count,
                   doubtful_players_count, data_confidence, snapshot_time
            FROM team_squad_snapshots
            WHERE team_id = %(team_id)s
              AND raw_json->>'official_match_id' = %(match_id)s
              AND raw_json->>'observation_type' = 'fixture_injuries'
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            {"team_id": team_id, "match_id": str(match_id)},
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "injured_players_count": row[0],
        "suspended_players_count": row[1],
        "doubtful_players_count": row[2],
        "data_confidence": row[3],
        "snapshot_time": row[4],
    }


# ---------------------------------------------------------------------------
# match_travel_features
# ---------------------------------------------------------------------------


def store_match_travel_features(conn: Any, travel: dict) -> int | None:
    """Upsert travel features by match_id."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM match_travel_features WHERE match_id = %(match_id)s",
            {"match_id": travel["match_id"]},
        )
        row = cur.fetchone()
        common = {
            "match_id": travel["match_id"],
            "home_team_id": travel.get("home_team_id"),
            "away_team_id": travel.get("away_team_id"),
            "stadium_id": travel.get("stadium_id"),
            "snapshot_time": travel.get("snapshot_time", _now()),
            "home_travel_distance_km": travel.get("home_travel_distance_km", 0),
            "away_travel_distance_km": travel.get("away_travel_distance_km"),
            "timezone_diff": travel.get("timezone_diff", 0),
            "altitude_diff_m": travel.get("altitude_diff_m", 0),
            "home_rest_days": travel.get("home_rest_days"),
            "away_rest_days": travel.get("away_rest_days"),
            "home_matches_last_7_days": travel.get("home_matches_last_7_days"),
            "away_matches_last_7_days": travel.get("away_matches_last_7_days"),
            "home_matches_last_14_days": travel.get("home_matches_last_14_days"),
            "away_matches_last_14_days": travel.get("away_matches_last_14_days"),
            "home_consecutive_away_games": travel.get("home_consecutive_away_games", 0),
            "away_consecutive_away_games": travel.get("away_consecutive_away_games", 0),
            "home_travel_fatigue_score": travel.get("home_travel_fatigue_score", 0),
            "away_travel_fatigue_score": travel.get("away_travel_fatigue_score"),
            "raw_json": json.dumps(travel.get("raw_json", {}), ensure_ascii=False),
        }
        if row:
            cur.execute(
                """
                UPDATE match_travel_features SET
                    home_team_id = %(home_team_id)s, away_team_id = %(away_team_id)s,
                    stadium_id = %(stadium_id)s, snapshot_time = %(snapshot_time)s,
                    home_travel_distance_km = %(home_travel_distance_km)s,
                    away_travel_distance_km = %(away_travel_distance_km)s,
                    timezone_diff = %(timezone_diff)s, altitude_diff_m = %(altitude_diff_m)s,
                    home_rest_days = %(home_rest_days)s, away_rest_days = %(away_rest_days)s,
                    home_matches_last_7_days = %(home_matches_last_7_days)s,
                    away_matches_last_7_days = %(away_matches_last_7_days)s,
                    home_matches_last_14_days = %(home_matches_last_14_days)s,
                    away_matches_last_14_days = %(away_matches_last_14_days)s,
                    home_consecutive_away_games = %(home_consecutive_away_games)s,
                    away_consecutive_away_games = %(away_consecutive_away_games)s,
                    home_travel_fatigue_score = %(home_travel_fatigue_score)s,
                    away_travel_fatigue_score = %(away_travel_fatigue_score)s,
                    raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO match_travel_features (
                    match_id, home_team_id, away_team_id, stadium_id, snapshot_time,
                    home_travel_distance_km, away_travel_distance_km,
                    timezone_diff, altitude_diff_m,
                    home_rest_days, away_rest_days,
                    home_matches_last_7_days, away_matches_last_7_days,
                    home_matches_last_14_days, away_matches_last_14_days,
                    home_consecutive_away_games, away_consecutive_away_games,
                    home_travel_fatigue_score, away_travel_fatigue_score, raw_json
                ) VALUES (
                    %(match_id)s, %(home_team_id)s, %(away_team_id)s, %(stadium_id)s, %(snapshot_time)s,
                    %(home_travel_distance_km)s, %(away_travel_distance_km)s,
                    %(timezone_diff)s, %(altitude_diff_m)s,
                    %(home_rest_days)s, %(away_rest_days)s,
                    %(home_matches_last_7_days)s, %(away_matches_last_7_days)s,
                    %(home_matches_last_14_days)s, %(away_matches_last_14_days)s,
                    %(home_consecutive_away_games)s, %(away_consecutive_away_games)s,
                    %(home_travel_fatigue_score)s, %(away_travel_fatigue_score)s, %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# team_motivation_snapshots
# ---------------------------------------------------------------------------


def store_team_motivation_snapshot(conn: Any, mot: dict) -> int | None:
    """Upsert motivation snapshot by (match_id, team_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM team_motivation_snapshots
            WHERE match_id = %(match_id)s AND team_id = %(team_id)s
            """,
            {"match_id": mot["match_id"], "team_id": mot["team_id"]},
        )
        row = cur.fetchone()
        common = {
            "match_id": mot["match_id"],
            "team_id": mot["team_id"],
            "competition_season_id": mot.get("competition_season_id"),
            "snapshot_time": mot.get("snapshot_time", _now()),
            "current_rank": mot.get("current_rank"),
            "current_points": mot.get("current_points"),
            "remaining_matches": mot.get("remaining_matches"),
            "title_race_score": mot.get("title_race_score"),
            "continental_race_score": mot.get("continental_race_score"),
            "promotion_score": mot.get("promotion_score"),
            "relegation_pressure_score": mot.get("relegation_pressure_score"),
            "mid_table_no_pressure_score": mot.get("mid_table_no_pressure_score"),
            "must_win": mot.get("must_win", False),
            "draw_enough": mot.get("draw_enough", False),
            "already_qualified": mot.get("already_qualified", False),
            "already_eliminated": mot.get("already_eliminated", False),
            "need_goal_difference": mot.get("need_goal_difference", False),
            "derby_motivation_score": mot.get("derby_motivation_score"),
            "revenge_motivation_score": mot.get("revenge_motivation_score"),
            "manager_pressure_score": mot.get("manager_pressure_score"),
            "final_motivation_score": mot.get("final_motivation_score"),
            "motivation_reason": json.dumps(mot.get("motivation_reason", {}), ensure_ascii=False),
            "raw_json": json.dumps(mot.get("raw_json", {}), ensure_ascii=False),
        }
        if row:
            cur.execute(
                """
                UPDATE team_motivation_snapshots SET
                    competition_season_id = %(competition_season_id)s,
                    snapshot_time = %(snapshot_time)s, current_rank = %(current_rank)s,
                    current_points = %(current_points)s, remaining_matches = %(remaining_matches)s,
                    title_race_score = %(title_race_score)s,
                    continental_race_score = %(continental_race_score)s,
                    promotion_score = %(promotion_score)s,
                    relegation_pressure_score = %(relegation_pressure_score)s,
                    mid_table_no_pressure_score = %(mid_table_no_pressure_score)s,
                    must_win = %(must_win)s, draw_enough = %(draw_enough)s,
                    already_qualified = %(already_qualified)s,
                    already_eliminated = %(already_eliminated)s,
                    need_goal_difference = %(need_goal_difference)s,
                    derby_motivation_score = %(derby_motivation_score)s,
                    revenge_motivation_score = %(revenge_motivation_score)s,
                    manager_pressure_score = %(manager_pressure_score)s,
                    final_motivation_score = %(final_motivation_score)s,
                    motivation_reason = %(motivation_reason)s, raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO team_motivation_snapshots (
                    match_id, team_id, competition_season_id, snapshot_time,
                    current_rank, current_points, remaining_matches,
                    title_race_score, continental_race_score, promotion_score,
                    relegation_pressure_score, mid_table_no_pressure_score,
                    must_win, draw_enough, already_qualified, already_eliminated,
                    need_goal_difference, derby_motivation_score, revenge_motivation_score,
                    manager_pressure_score, final_motivation_score,
                    motivation_reason, raw_json
                ) VALUES (
                    %(match_id)s, %(team_id)s, %(competition_season_id)s, %(snapshot_time)s,
                    %(current_rank)s, %(current_points)s, %(remaining_matches)s,
                    %(title_race_score)s, %(continental_race_score)s, %(promotion_score)s,
                    %(relegation_pressure_score)s, %(mid_table_no_pressure_score)s,
                    %(must_win)s, %(draw_enough)s, %(already_qualified)s, %(already_eliminated)s,
                    %(need_goal_difference)s, %(derby_motivation_score)s, %(revenge_motivation_score)s,
                    %(manager_pressure_score)s, %(final_motivation_score)s,
                    %(motivation_reason)s, %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_motivation_for_match(conn: Any, match_id: int) -> list[dict]:
    """Get motivation snapshots for both teams in a match."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT team_id, final_motivation_score, must_win, draw_enough,
                   already_qualified, already_eliminated, relegation_pressure_score
            FROM team_motivation_snapshots
            WHERE match_id = %s
            ORDER BY team_id
            """,
            (match_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "team_id": r[0],
            "final_motivation_score": r[1],
            "must_win": r[2],
            "draw_enough": r[3],
            "already_qualified": r[4],
            "already_eliminated": r[5],
            "relegation_pressure_score": r[6],
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# tournament_incentive_snapshots
# ---------------------------------------------------------------------------


def store_tournament_incentive_snapshot(conn: Any, snap: dict) -> int | None:
    """Upsert tournament incentive snapshot by (match_id, team_id)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM tournament_incentive_snapshots
            WHERE match_id = %(match_id)s AND team_id = %(team_id)s
            """,
            {"match_id": snap["match_id"], "team_id": snap["team_id"]},
        )
        row = cur.fetchone()
        common = {
            "match_id": snap["match_id"],
            "team_id": snap["team_id"],
            "snapshot_time": snap.get("snapshot_time", _now()),
            "current_group_rank": snap.get("current_group_rank"),
            "qualification_status": snap.get("qualification_status", ""),
            "potential_rank_if_win": snap.get("potential_rank_if_win"),
            "potential_rank_if_draw": snap.get("potential_rank_if_draw"),
            "potential_rank_if_loss": snap.get("potential_rank_if_loss"),
            "potential_opponents_if_win": json.dumps(snap.get("potential_opponents_if_win", [])),
            "potential_opponents_if_draw": json.dumps(snap.get("potential_opponents_if_draw", [])),
            "potential_opponents_if_loss": json.dumps(snap.get("potential_opponents_if_loss", [])),
            "bracket_difficulty_if_win": snap.get("bracket_difficulty_if_win"),
            "bracket_difficulty_if_draw": snap.get("bracket_difficulty_if_draw"),
            "bracket_difficulty_if_loss": snap.get("bracket_difficulty_if_loss"),
            "avoid_strong_opponent_score": snap.get("avoid_strong_opponent_score"),
            "tanking_risk_score": snap.get("tanking_risk_score"),
            "rotation_after_qualification_score": snap.get("rotation_after_qualification_score"),
            "incentive_summary": snap.get("incentive_summary", ""),
            "raw_json": json.dumps(snap.get("raw_json", {}), ensure_ascii=False),
        }
        if row:
            cur.execute(
                """
                UPDATE tournament_incentive_snapshots SET
                    snapshot_time = %(snapshot_time)s, current_group_rank = %(current_group_rank)s,
                    qualification_status = %(qualification_status)s,
                    potential_rank_if_win = %(potential_rank_if_win)s,
                    potential_rank_if_draw = %(potential_rank_if_draw)s,
                    potential_rank_if_loss = %(potential_rank_if_loss)s,
                    potential_opponents_if_win = %(potential_opponents_if_win)s,
                    potential_opponents_if_draw = %(potential_opponents_if_draw)s,
                    potential_opponents_if_loss = %(potential_opponents_if_loss)s,
                    bracket_difficulty_if_win = %(bracket_difficulty_if_win)s,
                    bracket_difficulty_if_draw = %(bracket_difficulty_if_draw)s,
                    bracket_difficulty_if_loss = %(bracket_difficulty_if_loss)s,
                    avoid_strong_opponent_score = %(avoid_strong_opponent_score)s,
                    tanking_risk_score = %(tanking_risk_score)s,
                    rotation_after_qualification_score = %(rotation_after_qualification_score)s,
                    incentive_summary = %(incentive_summary)s, raw_json = %(raw_json)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            return row[0]
        else:
            cur.execute(
                """
                INSERT INTO tournament_incentive_snapshots (
                    match_id, team_id, snapshot_time,
                    current_group_rank, qualification_status,
                    potential_rank_if_win, potential_rank_if_draw, potential_rank_if_loss,
                    potential_opponents_if_win, potential_opponents_if_draw,
                    potential_opponents_if_loss,
                    bracket_difficulty_if_win, bracket_difficulty_if_draw,
                    bracket_difficulty_if_loss,
                    avoid_strong_opponent_score, tanking_risk_score,
                    rotation_after_qualification_score, incentive_summary, raw_json
                ) VALUES (
                    %(match_id)s, %(team_id)s, %(snapshot_time)s,
                    %(current_group_rank)s, %(qualification_status)s,
                    %(potential_rank_if_win)s, %(potential_rank_if_draw)s, %(potential_rank_if_loss)s,
                    %(potential_opponents_if_win)s, %(potential_opponents_if_draw)s,
                    %(potential_opponents_if_loss)s,
                    %(bracket_difficulty_if_win)s, %(bracket_difficulty_if_draw)s,
                    %(bracket_difficulty_if_loss)s,
                    %(avoid_strong_opponent_score)s, %(tanking_risk_score)s,
                    %(rotation_after_qualification_score)s, %(incentive_summary)s, %(raw_json)s
                )
                RETURNING id
                """,
                common,
            )
            row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# season_standings_snapshots
# ---------------------------------------------------------------------------


def store_season_standings_snapshot(conn: Any, standing: dict) -> int | None:
    """Insert a standings snapshot (append-only — timestamped)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO season_standings_snapshots (
                competition_season_id, team_id, snapshot_time, round_no,
                rank, played, won, drawn, lost,
                goals_for, goals_against, goal_difference, points,
                home_points, away_points,
                title_race_score, continental_race_score,
                promotion_pressure_score, relegation_pressure_score,
                qualification_pressure_score, no_pressure_score,
                source_name, source_confidence, raw_json
            ) VALUES (
                %(competition_season_id)s, %(team_id)s, %(snapshot_time)s, %(round_no)s,
                %(rank)s, %(played)s, %(won)s, %(drawn)s, %(lost)s,
                %(goals_for)s, %(goals_against)s, %(goal_difference)s, %(points)s,
                %(home_points)s, %(away_points)s,
                %(title_race_score)s, %(continental_race_score)s,
                %(promotion_pressure_score)s, %(relegation_pressure_score)s,
                %(qualification_pressure_score)s, %(no_pressure_score)s,
                %(source_name)s, %(source_confidence)s, %(raw_json)s
            )
            RETURNING id
            """,
            {
                "competition_season_id": standing["competition_season_id"],
                "team_id": standing["team_id"],
                "snapshot_time": standing.get("snapshot_time", _now()),
                "round_no": standing.get("round_no"),
                "rank": standing.get("rank"),
                "played": standing.get("played"),
                "won": standing.get("won"),
                "drawn": standing.get("drawn"),
                "lost": standing.get("lost"),
                "goals_for": standing.get("goals_for"),
                "goals_against": standing.get("goals_against"),
                "goal_difference": standing.get("goal_difference"),
                "points": standing.get("points"),
                "home_points": standing.get("home_points"),
                "away_points": standing.get("away_points"),
                "title_race_score": standing.get("title_race_score", 0),
                "continental_race_score": standing.get("continental_race_score", 0),
                "promotion_pressure_score": standing.get("promotion_pressure_score", 0),
                "relegation_pressure_score": standing.get("relegation_pressure_score", 0),
                "qualification_pressure_score": standing.get("qualification_pressure_score", 0),
                "no_pressure_score": standing.get("no_pressure_score", 0),
                "source_name": standing.get("source_name", "football-data.org"),
                "source_confidence": standing.get("source_confidence", 0.85),
                "raw_json": json.dumps(standing.get("raw_json", {}), ensure_ascii=False),
            },
        )
        row = cur.fetchone()
    conn.commit()
    return row[0] if row else None


def get_latest_standings(conn: Any, competition_season_id: int) -> list[dict]:
    """Get latest standings for a competition season (one row per team)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (team_id)
                team_id, rank, played, won, drawn, lost,
                goals_for, goals_against, goal_difference, points,
                home_points, away_points, snapshot_time
            FROM season_standings_snapshots
            WHERE competition_season_id = %s
            ORDER BY team_id, snapshot_time DESC
            """,
            (competition_season_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "team_id": r[0],
            "rank": r[1],
            "played": r[2],
            "won": r[3],
            "drawn": r[4],
            "lost": r[5],
            "goals_for": r[6],
            "goals_against": r[7],
            "goal_difference": r[8],
            "points": r[9],
            "home_points": r[10],
            "away_points": r[11],
            "snapshot_time": r[12],
        }
        for r in rows
    ]
