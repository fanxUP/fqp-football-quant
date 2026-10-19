from datetime import datetime
from unittest.mock import MagicMock, patch

from scripts.features.build_weather_features import build_weather_for_match


def test_weather_forecast_uses_business_timezone_for_naive_database_kickoff(monkeypatch):
    monkeypatch.setenv("FQP_TIMEZONE", "Asia/Shanghai")
    client = MagicMock()
    client.get_forecast.return_value = {
        "temperature_2m": 20.0,
        "relative_humidity_2m": 60.0,
        "precipitation": 0.0,
        "wind_speed_10m": 5.0,
        "wind_gusts_10m": 8.0,
    }

    with patch("scripts.features.build_weather_features.store_match_weather_snapshot"):
        result = build_weather_for_match(
            conn=MagicMock(),
            match_id=22550,
            kickoff_time=datetime(2026, 7, 19, 0, 0),
            stadium_lat=62.7334,
            stadium_lon=7.1481,
            stadium_id=50,
            client=client,
        )

    assert result and result["has_weather"] is True
    assert result["weather_persisted"] is True
    client.get_forecast.assert_called_once_with(
        62.7334,
        7.1481,
        "2026-07-19T00:00:00",
        timezone="Asia/Shanghai",
    )


def test_weather_database_failure_does_not_publish_unpersisted_values():
    client = MagicMock()
    client.get_forecast.return_value = {"temperature_2m": 0, "precipitation": 0}
    with patch(
        "scripts.features.build_weather_features.store_match_weather_snapshot",
        side_effect=RuntimeError("fixed persistence failure"),
    ):
        result = build_weather_for_match(
            conn=MagicMock(),
            match_id=1,
            kickoff_time=datetime(2026, 10, 20, 20),
            stadium_lat=1,
            stadium_lon=2,
            client=client,
        )
    assert result["has_weather"] is False
    assert result["weather_persisted"] is False
    assert result["temperature_2m"] is None
