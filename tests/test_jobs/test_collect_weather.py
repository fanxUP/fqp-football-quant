from datetime import datetime
from unittest.mock import MagicMock, patch

from scripts.jobs.collect_weather import _run_impl


def test_collection_resolves_official_match_location_before_fetching_weather():
    conn = MagicMock()
    cur = MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [
        (
            22057,
            "法国",
            "英格兰",
            datetime(2026, 7, 19, 5, 0),
            {"remark": "比赛将在美国-佛罗里达州迈阿密加登斯举行"},
        )
    ]
    location = {
        "stadium_id": 11,
        "latitude": 25.958,
        "longitude": -80.238,
        "source": "official_venue_remark",
    }

    with (
        patch("scripts.jobs.collect_weather.get_db", return_value=conn),
        patch(
            "scripts.jobs.collect_weather.resolve_match_stadium_location",
            return_value=location,
        ) as resolver,
        patch(
            "scripts.jobs.collect_weather.build_weather_for_match",
            return_value={"has_weather": True},
        ) as builder,
        patch("scripts.jobs.collect_weather.OpenMeteoClient"),
    ):
        result = _run_impl()

    assert result["weather_fetched"] == 1
    assert result["skipped"] == 0
    resolver.assert_called_once_with(conn, cur.fetchall.return_value[0][4], "法国")
    assert builder.call_args.kwargs["stadium_id"] == 11
