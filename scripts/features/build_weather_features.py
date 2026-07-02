"""天气特征构建器。

从 Open-Meteo 获取比赛日天气，计算天气影响评分，写入 match_weather_snapshots。

核心公式（来自 build_travel_weather_features.py 骨架）：
  - weather_impact_score: 0-100，综合降水/风速/温度/湿度影响
  - goal_expectation_adjustment: 对预期进球的调节量
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.feature_storage import store_match_weather_snapshot
from scripts.openmeteo_client import OpenMeteoClient


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Weather impact computation (from skeleton build_travel_weather_features.py)
# ---------------------------------------------------------------------------


def compute_weather_impact(weather: dict[str, Any]) -> dict[str, float]:
    """Compute weather impact scores from raw weather data.

    Formula weights:
      - Rain/precipitation: 30% of impact
      - Wind speed: 25%
      - Wind gusts: 15%
      - Extreme temperature (>28°C): 15%
      - High humidity (>75%): 15%

    Returns:
        Dict with weather_impact_score, tempo_penalty_score,
        goal_expectation_adjustment, uncertainty_adjustment.
    """
    rain = float(weather.get("precipitation") or weather.get("rain") or 0)
    wind = float(weather.get("wind_speed_10m") or 0)
    gust = float(weather.get("wind_gusts_10m") or 0)
    temp = float(weather.get("temperature_2m") or 18)
    humidity = float(weather.get("relative_humidity_2m") or 60)

    impact = 0.0
    impact += min(rain / 15.0, 1.0) * 30
    impact += min(wind / 35.0, 1.0) * 25
    impact += min(gust / 50.0, 1.0) * 15
    impact += max(0.0, (temp - 28) / 12.0) * 15
    impact += max(0.0, (humidity - 75) / 25.0) * 15
    impact = max(0.0, min(100.0, impact))

    return {
        "weather_impact_score": round(impact, 4),
        "tempo_penalty_score": round(impact * 0.6, 4),
        "goal_expectation_adjustment": round(-impact / 1000.0, 6),
        "uncertainty_adjustment": round(impact / 500.0, 6),
    }


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------


def build_weather_for_match(
    conn: Any,
    match_id: int,
    kickoff_time: Any,  # datetime or ISO string
    stadium_lat: float | None = None,
    stadium_lon: float | None = None,
    stadium_id: int | None = None,
    client: OpenMeteoClient | None = None,
) -> dict[str, Any] | None:
    """Build weather features for a single match.

    Args:
        conn: DB connection.
        match_id: Official match ID.
        kickoff_time: Match kickoff datetime.
        stadium_lat: Stadium latitude (from stadiums table or known coords).
        stadium_lon: Stadium longitude.
        stadium_id: Stadium DB ID.
        client: Optional pre-created OpenMeteoClient (reuse across matches).

    Returns:
        Weather features dict for snapshot assembly, or None if no coords.
    """
    # Resolve coordinates
    lat = stadium_lat
    lon = stadium_lon

    if lat is None or lon is None:
        # Try to find from DB
        if stadium_id:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT latitude, longitude FROM stadiums WHERE id = %s",
                    (stadium_id,),
                )
                row = cur.fetchone()
                if row and row[0] is not None and row[1] is not None:
                    lat = float(row[0])
                    lon = float(row[1])

    if lat is None or lon is None:
        print(f"[weather] no coordinates for match {match_id}, skipping")
        return None

    # Normalize kickoff time to ISO string
    if isinstance(kickoff_time, datetime):
        kickoff_str = kickoff_time.isoformat()
    else:
        kickoff_str = str(kickoff_time)

    # Fetch weather
    own_client = client is None
    if own_client:
        client = OpenMeteoClient()

    try:
        if client is None:
            raise RuntimeError("OpenMeteoClient is not available")
        weather_data = client.get_forecast(lat, lon, kickoff_str)
    except Exception as e:
        print(f"[weather] OpenMeteo failed for match {match_id}: {e}")
        if own_client and client:
            client.close()
        return None

    if own_client and client:
        client.close()

    if weather_data.get("temperature_2m") is None:
        print(f"[weather] no weather data returned for match {match_id}")
        return {
            "temperature_2m": None,
            "precipitation": None,
            "wind_speed_10m": None,
            "weather_impact_score": None,
            "goal_expectation_weather_adjustment": None,
            "has_weather": False,
        }

    # Compute impact scores
    impact = compute_weather_impact(weather_data)

    # Store in DB
    try:
        store_match_weather_snapshot(
            conn,
            {
                "match_id": match_id,
                "stadium_id": stadium_id,
                "snapshot_time": _now(),
                "forecast_for_time": kickoff_str,
                "temperature_2m": weather_data.get("temperature_2m"),
                "apparent_temperature": weather_data.get("apparent_temperature"),
                "relative_humidity_2m": weather_data.get("relative_humidity_2m"),
                "precipitation": weather_data.get("precipitation"),
                "rain": weather_data.get("rain"),
                "snowfall": weather_data.get("snowfall"),
                "wind_speed_10m": weather_data.get("wind_speed_10m"),
                "wind_gusts_10m": weather_data.get("wind_gusts_10m"),
                "surface_pressure": weather_data.get("surface_pressure"),
                "cloud_cover": weather_data.get("cloud_cover"),
                "weather_impact_score": impact["weather_impact_score"],
                "tempo_penalty_score": impact["tempo_penalty_score"],
                "goal_expectation_adjustment": impact["goal_expectation_adjustment"],
                "uncertainty_adjustment": impact["uncertainty_adjustment"],
                "source_name": "open-meteo",
                "source_confidence": 0.85,
                "raw_json": weather_data,
            },
        )
    except Exception as e:
        print(f"[weather] DB store failed for match {match_id}: {e}")

    return {
        "temperature_2m": weather_data.get("temperature_2m"),
        "precipitation": weather_data.get("precipitation"),
        "wind_speed_10m": weather_data.get("wind_speed_10m"),
        "weather_impact_score": impact["weather_impact_score"],
        "goal_expectation_weather_adjustment": impact["goal_expectation_adjustment"],
        "has_weather": True,
        "weather_source": "open-meteo",
    }


def build_weather_for_matches(
    conn: Any,
    matches: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build weather features for a batch of matches.

    Args:
        conn: DB connection.
        matches: List of match dicts, each with:
            - id (match_id)
            - kickoff_time
            - stadium_id (optional)
            - stadium_lat (optional)
            - stadium_lon (optional)

    Returns:
        Summary dict with counts.
    """
    client = OpenMeteoClient()
    success = 0
    skipped = 0
    failed = 0

    try:
        for match in matches:
            result = build_weather_for_match(
                conn=conn,
                match_id=match["id"],
                kickoff_time=match.get("kickoff_time"),
                stadium_lat=match.get("stadium_lat"),
                stadium_lon=match.get("stadium_lon"),
                stadium_id=match.get("stadium_id"),
                client=client,
            )
            if result is None:
                skipped += 1
            elif result.get("has_weather"):
                success += 1
            else:
                failed += 1
    finally:
        client.close()

    return {
        "status": "ok",
        "matches_processed": len(matches),
        "weather_fetched": success,
        "skipped_no_coords": skipped,
        "failed": failed,
    }
