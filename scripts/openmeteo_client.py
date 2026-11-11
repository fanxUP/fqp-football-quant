"""Open-Meteo free weather API client.

No API key required. Free for non-commercial use, 10,000 requests/day.
Provides hourly forecasts and historical weather data.

Key endpoints:
  /v1/forecast    → hourly forecast (temperature, precipitation, wind, etc.)
  /v1/archive     → historical weather for backtesting

For football FQP:
  - Match-day weather at stadium location
  - Temperature extremes → goal expectation adjustment
  - Precipitation → match randomness
  - Wind speed → long-ball effectiveness
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

import httpx

# Weather variables relevant to football matches
FORECAST_VARIABLES = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "wind_speed_10m",
    "wind_gusts_10m",
    "surface_pressure",
    "cloud_cover",
]


class OpenMeteoClient:
    """HTTP client for api.open-meteo.com — free, no auth required."""

    BASE_URL = "https://api.open-meteo.com/v1/"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/"

    # Well-known football stadiums with coordinates
    # Used as fallback when DB doesn't have stadium data yet
    STADIUM_COORDS: dict[str, tuple[float, float]] = {
        "Wembley Stadium": (51.556, -0.279),
        "Old Trafford": (53.463, -2.291),
        "Anfield": (53.431, -2.961),
        "Emirates Stadium": (51.555, -0.108),
        "Stamford Bridge": (51.482, -0.191),
        "Etihad Stadium": (53.483, -2.200),
        "Tottenham Hotspur Stadium": (51.604, -0.066),
        "Santiago Bernabeu": (40.453, -3.688),
        "Camp Nou": (41.381, 2.123),
        "Allianz Arena": (48.219, 11.625),
        "Signal Iduna Park": (51.493, 7.452),
        "Parc des Princes": (48.841, 2.253),
        "San Siro": (45.478, 9.124),
        "Allianz Stadium": (45.109, 7.641),
        "Johan Cruijff ArenA": (52.314, 4.942),
        "Estadio da Luz": (38.753, -9.185),
        "Estadio do Dragao": (41.162, -8.583),
    }

    def __init__(
        self,
        timeout: float = 30.0,
        min_interval: float = 0.3,  # generous: ~200 req/min, far below 10k/day
        max_retries: int = 3,
    ) -> None:
        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _request(
        self, url: str, params: dict[str, Any], use_archive: bool = False
    ) -> dict[str, Any]:
        """GET request with exponential backoff retry."""
        self._rate_limit()
        base = self.ARCHIVE_URL if use_archive else self.BASE_URL
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(f"[openmeteo] GET {url} (attempt {attempt})")
                # Reuse the long-lived client so batch collection keeps HTTP
                # connections warm instead of paying a new TLS handshake for
                # every match. A full URL also supports the archive host.
                resp = self._client.get(
                    f"{base}{url}",
                    params=params,
                )
                self._last_request_time = time.monotonic()

                if resp.status_code == 429:
                    wait = 60
                    print(f"[openmeteo] rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()
                print(f"[openmeteo] GET {url} → {resp.status_code}")
                return data
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                last_error = e
                print(f"[openmeteo] GET {url} error (attempt {attempt}): {e}")
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[openmeteo] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"OpenMeteoClient: {self._max_retries} attempts failed for {url}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Hourly data extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_match_window(
        hourly: dict[str, list[Any]],
        match_time: str,  # ISO format
        window_hours: int = 3,
        timezone: str = "auto",
    ) -> dict[str, float | None]:
        """Extract weather data around match kickoff time.

        Averages the hourly values within a [kickoff, kickoff+window_hours] window.
        Falls back to the closest hour if exact match not found.
        """
        times = hourly.get("time", [])
        if not times:
            return {}

        # Parse match time and find the closest hour index
        match_dt = datetime.fromisoformat(match_time.replace("Z", "+00:00"))
        match_hour = match_dt.replace(minute=0, second=0, microsecond=0)

        closest_idx = None
        min_diff = float("inf")
        for i, t_str in enumerate(times):
            t = datetime.fromisoformat(t_str.replace("Z", "+00:00"))
            diff = abs((t - match_hour).total_seconds())
            if diff < min_diff:
                min_diff = diff
                closest_idx = i

        if closest_idx is None:
            return {}

        # Average values over the match window
        end_idx = min(closest_idx + window_hours, len(times))
        result: dict[str, float | None] = {}
        for var_name in FORECAST_VARIABLES:
            values = hourly.get(var_name, [])
            if values:
                window_values = [v for v in values[closest_idx:end_idx] if v is not None]
                if window_values:
                    result[var_name] = round(sum(window_values) / len(window_values), 2)

        return result

    # ------------------------------------------------------------------
    # Public API — Forecast
    # ------------------------------------------------------------------

    def get_forecast(
        self,
        latitude: float,
        longitude: float,
        match_time: str,  # ISO format kickoff time
        timezone: str = "auto",
        past_days: int = 0,
        forecast_days: int = 7,
    ) -> dict[str, Any]:
        """Get weather forecast for a match at the stadium location.

        Args:
            latitude: Stadium latitude.
            longitude: Stadium longitude.
            match_time: ISO-format kickoff time (e.g. '2026-07-03T19:45:00').
            timezone: Timezone string or 'auto' for automatic detection.
            past_days: Days of past data to include (for nowcasting).
            forecast_days: Days of forecast to request (max 16).

        Returns:
            Dict with 'temperature_2m', 'precipitation', 'wind_speed_10m', etc.
            plus 'match_window_*' keys with match-specific averages.
        """
        # Determine the date range
        try:
            match_dt = datetime.fromisoformat(match_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            match_dt = datetime.now() + timedelta(days=1)

        start_date = (match_dt - timedelta(days=max(past_days, 1))).strftime("%Y-%m-%d")
        end_date = (match_dt + timedelta(days=min(forecast_days, 16))).strftime("%Y-%m-%d")

        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(FORECAST_VARIABLES),
            "timezone": timezone,
            "start_date": start_date,
            "end_date": end_date,
        }

        data = self._request("forecast", params)

        # Extract match-window values
        hourly = data.get("hourly", {})
        match_window = self._extract_match_window(hourly, match_time)

        return {
            "latitude": data.get("latitude", latitude),
            "longitude": data.get("longitude", longitude),
            "timezone": data.get("timezone", timezone),
            "match_time": match_time,
            "temperature_2m": match_window.get("temperature_2m"),
            "apparent_temperature": match_window.get("apparent_temperature"),
            "relative_humidity_2m": match_window.get("relative_humidity_2m"),
            "precipitation": match_window.get("precipitation"),
            "rain": match_window.get("rain"),
            "snowfall": match_window.get("snowfall"),
            "wind_speed_10m": match_window.get("wind_speed_10m"),
            "wind_gusts_10m": match_window.get("wind_gusts_10m"),
            "surface_pressure": match_window.get("surface_pressure"),
            "cloud_cover": match_window.get("cloud_cover"),
            "raw_hourly": {
                "time": hourly.get("time", []),
                "temperature_2m": hourly.get("temperature_2m", []),
                "precipitation": hourly.get("precipitation", []),
                "wind_speed_10m": hourly.get("wind_speed_10m", []),
            },
            "_match_window": match_window,
        }

    # ------------------------------------------------------------------
    # Public API — Historical Weather
    # ------------------------------------------------------------------

    def get_historical_weather(
        self,
        latitude: float,
        longitude: float,
        match_time: str,
        timezone: str = "auto",
    ) -> dict[str, Any]:
        """Get historical weather for a past match (backtesting).

        Uses the archive API to retrieve observed weather.
        """
        try:
            match_dt = datetime.fromisoformat(match_time.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            match_dt = datetime.now() - timedelta(days=7)

        date_str = match_dt.strftime("%Y-%m-%d")

        params: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": ",".join(FORECAST_VARIABLES),
            "timezone": timezone,
        }

        data = self._request("archive", params, use_archive=True)

        hourly = data.get("hourly", {})
        match_window = self._extract_match_window(hourly, match_time)

        return {
            "latitude": data.get("latitude", latitude),
            "longitude": data.get("longitude", longitude),
            "match_time": match_time,
            "temperature_2m": match_window.get("temperature_2m"),
            "precipitation": match_window.get("precipitation"),
            "wind_speed_10m": match_window.get("wind_speed_10m"),
            "wind_gusts_10m": match_window.get("wind_gusts_10m"),
            "relative_humidity_2m": match_window.get("relative_humidity_2m"),
            "raw_hourly": {
                "time": hourly.get("time", []),
                "temperature_2m": hourly.get("temperature_2m", []),
                "precipitation": hourly.get("precipitation", []),
                "wind_speed_10m": hourly.get("wind_speed_10m", []),
            },
            "_match_window": match_window,
        }

    # ------------------------------------------------------------------
    # Stadium helpers
    # ------------------------------------------------------------------

    def get_stadium_forecast(
        self,
        stadium_name: str,
        match_time: str,
        latitude: float | None = None,
        longitude: float | None = None,
        timezone: str = "auto",
    ) -> dict[str, Any] | None:
        """Get forecast for a named stadium.

        Uses provided coordinates, or falls back to built-in STADIUM_COORDS.
        """
        if latitude is not None and longitude is not None:
            return self.get_forecast(latitude, longitude, match_time, timezone)

        coords = self.STADIUM_COORDS.get(stadium_name)
        if coords:
            return self.get_forecast(coords[0], coords[1], match_time, timezone)

        print(f"[openmeteo] no coordinates for stadium: {stadium_name}")
        return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()
