"""Shared schedule metadata for the bounded weather collector."""

WEATHER_COLLECTION_INTERVAL_HOURS = 4
WEATHER_COLLECTION_MINUTE = 7
WEATHER_COLLECTION_TIMEZONE = "Asia/Shanghai"
WEATHER_COLLECTION_HOURS = tuple(range(0, 24, WEATHER_COLLECTION_INTERVAL_HOURS))
_WEATHER_COLLECTION_CLOCKS = tuple(
    f"{hour:02d}:{WEATHER_COLLECTION_MINUTE:02d}" for hour in WEATHER_COLLECTION_HOURS
)
_WEATHER_COLLECTION_TIMEZONE_LABEL = (
    "北京时间" if WEATHER_COLLECTION_TIMEZONE == "Asia/Shanghai" else WEATHER_COLLECTION_TIMEZONE
)
WEATHER_COLLECTION_SCHEDULE = (
    f"每{WEATHER_COLLECTION_INTERVAL_HOURS}小时"
    f"（{'/'.join(_WEATHER_COLLECTION_CLOCKS)}，{_WEATHER_COLLECTION_TIMEZONE_LABEL}）"
)


def weather_collection_cron() -> dict[str, int | str]:
    """Return the Asia/Shanghai APScheduler cron fields for weather refresh."""
    return {
        "hour": ",".join(str(hour) for hour in WEATHER_COLLECTION_HOURS),
        "minute": WEATHER_COLLECTION_MINUTE,
        "timezone": WEATHER_COLLECTION_TIMEZONE,
    }
