"""旅行疲劳与天气影响特征骨架。"""

from __future__ import annotations

import math
from typing import Any


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_travel_fatigue(
    distance_km: float, timezone_diff: float, rest_days: int, consecutive_away: int
) -> float:
    distance_score = min(distance_km / 2000.0, 1.0) * 100
    timezone_score = min(abs(timezone_diff) / 4.0, 1.0) * 100
    rest_score = max(0, 4 - rest_days) / 4 * 100
    away_score = min(consecutive_away / 3.0, 1.0) * 100
    return distance_score * 0.30 + timezone_score * 0.25 + rest_score * 0.25 + away_score * 0.20


def compute_weather_impact(weather: dict[str, Any]) -> dict[str, float]:
    rain = float(weather.get("precipitation") or 0)
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
        "weather_impact_score": impact,
        "tempo_penalty_score": impact * 0.6,
        "goal_expectation_adjustment": -impact / 1000.0,
        "uncertainty_adjustment": impact / 500.0,
    }
