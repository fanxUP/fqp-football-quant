"""Official Sporttery football sales-window rules.

Sporttery publishes match-level sale flags separately from its nationwide
retail sales hours.  A match is actionable only when both are open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any

from scripts.business_time import business_now

WEEKDAY_OPEN_TIME = time(11, 0)
WEEKDAY_CLOSE_TIME = time(22, 0)
WEEKEND_OPEN_TIME = time(11, 0)
WEEKEND_CLOSE_TIME = time(23, 0)


@dataclass(frozen=True)
class SportterySalesWindow:
    is_open: bool
    current_time: datetime
    opens_at: datetime
    closes_at: datetime
    next_opens_at: datetime
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "is_open": self.is_open,
            "current_time": self.current_time.isoformat(),
            "opens_at": self.opens_at.isoformat(),
            "closes_at": self.closes_at.isoformat(),
            "next_opens_at": self.next_opens_at.isoformat(),
            "message": self.message,
            "schedule": {
                "weekday": "11:00-22:00",
                "weekend": "11:00-23:00",
                "timezone": "Asia/Shanghai",
            },
        }


def _day_window(current: datetime) -> tuple[datetime, datetime]:
    weekend = current.weekday() >= 5
    open_at = WEEKEND_OPEN_TIME if weekend else WEEKDAY_OPEN_TIME
    close_at = WEEKEND_CLOSE_TIME if weekend else WEEKDAY_CLOSE_TIME
    return current.replace(
        hour=open_at.hour,
        minute=open_at.minute,
        second=0,
        microsecond=0,
    ), current.replace(
        hour=close_at.hour,
        minute=close_at.minute,
        second=0,
        microsecond=0,
    )


def get_sporttery_sales_window(value: datetime | None = None) -> SportterySalesWindow:
    """Return the effective official football sales window in Shanghai time."""
    current = business_now(value)
    opens_at, closes_at = _day_window(current)
    is_open = opens_at <= current < closes_at

    if current < opens_at:
        next_opens_at = opens_at
        reopen_label = "今日"
    elif current >= closes_at:
        next_day = current + timedelta(days=1)
        next_opens_at, _ = _day_window(next_day)
        reopen_label = "明日"
    else:
        next_opens_at = opens_at
        reopen_label = "今日"

    message = (
        f"官方竞彩开售中，今日 {closes_at:%H:%M} 停售"
        if is_open
        else f"官方竞彩休市中，{reopen_label} {next_opens_at:%H:%M} 恢复开售"
    )
    return SportterySalesWindow(
        is_open=is_open,
        current_time=current,
        opens_at=opens_at,
        closes_at=closes_at,
        next_opens_at=next_opens_at,
        message=message,
    )
