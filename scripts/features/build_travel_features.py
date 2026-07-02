"""旅行疲劳与地理特征构建器。

从 stadiums 表读取球场坐标，计算:
  - haversine 客场旅行距离
  - 时区差/海拔差
  - 旅行疲劳评分

核心公式（来自 build_travel_weather_features.py 骨架）:
  - haversine_km(lat1, lon1, lat2, lon2) → 大圆距离
  - compute_travel_fatigue(distance, timezone_diff, rest_days, consecutive_away)

输出字段（写入 match_feature_snapshots）:
  - stadium_id
  - away_travel_distance_km
  - timezone_diff
  - altitude_m
  - away_travel_fatigue_score
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from scripts.feature_storage import store_match_travel_features


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance in km between two coordinates."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_travel_fatigue(
    distance_km: float,
    timezone_diff: float,
    rest_days: int,
    consecutive_away: int,
) -> float:
    """Compute travel fatigue score (0-100).

    Weighted formula:
      - distance_score (30%): normalized to 2000km
      - timezone_score (25%): normalized to 4h difference
      - rest_score (25%): 4 - rest_days, normalized to 4
      - away_score (20%): consecutive away games, normalized to 3
    """
    distance_score = min(distance_km / 2000.0, 1.0) * 100
    timezone_score = min(abs(timezone_diff) / 4.0, 1.0) * 100
    rest_score = max(0, 4 - rest_days) / 4 * 100
    away_score = min(consecutive_away / 3.0, 1.0) * 100
    return round(
        distance_score * 0.30 + timezone_score * 0.25 + rest_score * 0.25 + away_score * 0.20,
        4,
    )


def _get_stadium_coords(
    conn: Any, stadium_id: int | None
) -> tuple[float, float, float, str] | None:
    """Get stadium latitude, longitude, altitude, timezone from DB."""
    if not stadium_id:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT latitude, longitude, altitude_m, timezone FROM stadiums WHERE id = %s",
            (stadium_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return (
        float(row[0]) if row[0] else 0.0,
        float(row[1]) if row[1] else 0.0,
        float(row[2]) if row[2] else 0.0,
        row[3] or "",
    )


def _count_consecutive_away(conn: Any, team_id: int, before_date: str) -> int:
    """Count consecutive away games for a team before a given date."""
    # Simplified: count away matches in the last 14 days
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM official_matches m
            WHERE (m.home_team_name IN (SELECT alias_name FROM team_aliases WHERE team_id = %(team_id)s)
                   OR m.away_team_name IN (SELECT alias_name FROM team_aliases WHERE team_id = %(team_id)s))
              AND m.kickoff_time < %(before)s
              AND m.kickoff_time > %(before)s::timestamp - INTERVAL '14 days'
            """,
            {"team_id": team_id, "before": before_date},
        )
        row = cur.fetchone()
    return row[0] if row else 0


def build_travel_features(
    conn: Any,
    match_id: int,
    home_team_id: int | None,
    away_team_id: int | None,
    match_stadium_id: int | None = None,
    kickoff_time: Any = None,
) -> dict[str, Any]:
    """Build travel/geography features for a match.

    Args:
        conn: DB connection.
        match_id: Match ID.
        home_team_id: Home team ID.
        away_team_id: Away team ID.
        match_stadium_id: The stadium where the match is played.
        kickoff_time: Match kickoff time for consecutive away game counting.

    Returns:
        Dict with travel fields for snapshot assembly.
    """
    # Get stadium coordinates
    match_coords = _get_stadium_coords(conn, match_stadium_id)

    # Get home/away team home stadiums
    home_stadium_id = None
    away_stadium_id = None
    if home_team_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stadium_id FROM team_stadium_history
                WHERE team_id = %s
                ORDER BY valid_from DESC LIMIT 1
                """,
                (home_team_id,),
            )
            row = cur.fetchone()
            home_stadium_id = row[0] if row else None

    if away_team_id:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT stadium_id FROM team_stadium_history
                WHERE team_id = %s
                ORDER BY valid_from DESC LIMIT 1
                """,
                (away_team_id,),
            )
            row = cur.fetchone()
            away_stadium_id = row[0] if row else None

    home_coords = _get_stadium_coords(conn, home_stadium_id)
    away_coords = _get_stadium_coords(conn, away_stadium_id)

    # Compute distances
    home_travel_km = 0.0
    away_travel_km = 0.0
    timezone_diff_val = 0.0
    altitude_diff = 0.0

    if match_coords and away_coords:
        away_travel_km = round(
            haversine_km(
                away_coords[0],
                away_coords[1],
                match_coords[0],
                match_coords[1],
            ),
            2,
        )
        timezone_diff_val = 0.0  # simplified: need timezone offset computation
        altitude_diff = (
            round(match_coords[2] - away_coords[2], 2)
            if match_coords[2] and away_coords[2]
            else 0.0
        )

    # Home team rarely travels; if they do, it's neutral venue
    if match_coords and home_coords:
        home_dist = haversine_km(
            home_coords[0],
            home_coords[1],
            match_coords[0],
            match_coords[1],
        )
        if home_dist > 50:  # neutral venue
            home_travel_km = round(home_dist, 2)

    # Consecutive away games
    kt_str = (
        kickoff_time.isoformat()
        if isinstance(kickoff_time, datetime)
        else str(kickoff_time or _now())
    )
    home_consecutive = 0
    away_consecutive = 0
    if home_team_id:
        try:
            home_consecutive = _count_consecutive_away(conn, home_team_id, kt_str)
        except Exception:
            pass
    if away_team_id:
        try:
            away_consecutive = _count_consecutive_away(conn, away_team_id, kt_str)
        except Exception:
            pass

    # Travel fatigue
    away_fatigue = (
        compute_travel_fatigue(away_travel_km, timezone_diff_val, 3, away_consecutive)
        if away_travel_km > 0
        else 0.0
    )
    home_fatigue = (
        compute_travel_fatigue(home_travel_km, 0, 3, home_consecutive)
        if home_travel_km > 50
        else 0.0
    )

    # Store in DB
    try:
        store_match_travel_features(
            conn,
            {
                "match_id": match_id,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                "stadium_id": match_stadium_id,
                "snapshot_time": _now(),
                "home_travel_distance_km": home_travel_km,
                "away_travel_distance_km": away_travel_km,
                "timezone_diff": timezone_diff_val,
                "altitude_diff_m": altitude_diff,
                "home_consecutive_away_games": home_consecutive,
                "away_consecutive_away_games": away_consecutive,
                "home_travel_fatigue_score": home_fatigue,
                "away_travel_fatigue_score": away_fatigue,
                "raw_json": {},
            },
        )
    except Exception as e:
        print(f"[travel] DB store error for match {match_id}: {e}")

    has_travel = away_travel_km > 0 or home_travel_km > 50

    return {
        "stadium_id": match_stadium_id,
        "away_travel_distance_km": away_travel_km if away_travel_km > 0 else None,
        "timezone_diff": timezone_diff_val if timezone_diff_val != 0 else None,
        "altitude_m": match_coords[2] if match_coords else None,
        "away_travel_fatigue_score": away_fatigue if away_fatigue > 0 else None,
        "has_travel_data": has_travel,
    }
