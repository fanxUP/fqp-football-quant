from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.sporttery_sales import get_sporttery_sales_window


def shanghai_time(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_weekday_sales_window_is_11_to_22_shanghai_time():
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 17, 10, 59)).is_open is False
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 17, 11)).is_open is True
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 17, 21, 59)).is_open is True
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 17, 22)).is_open is False


def test_weekend_sales_window_is_11_to_23_shanghai_time():
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 18, 10, 59)).is_open is False
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 18, 11)).is_open is True
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 18, 22, 59)).is_open is True
    assert get_sporttery_sales_window(shanghai_time(2026, 7, 18, 23)).is_open is False


def test_sunday_overnight_rest_points_to_same_day_opening():
    status = get_sporttery_sales_window(shanghai_time(2026, 7, 19, 2, 9))

    assert status.is_open is False
    assert status.current_time.isoformat() == "2026-07-19T02:09:00+08:00"
    assert status.next_opens_at.isoformat() == "2026-07-19T11:00:00+08:00"
    assert status.message == "官方竞彩休市中，今日 11:00 恢复开售"


def test_after_closing_points_to_next_day_opening():
    status = get_sporttery_sales_window(shanghai_time(2026, 7, 19, 23, 30))

    assert status.is_open is False
    assert status.next_opens_at.isoformat() == "2026-07-20T11:00:00+08:00"
    assert status.message == "官方竞彩休市中，明日 11:00 恢复开售"
