"""Official traditional-lottery windows; naive schedule times mean Shanghai."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from scripts.business_time import business_now, business_timezone

STOP_FIELDS = ("saleEndTime", "lotterySaleEndtime", "lotterySaleEndTime")
START_FIELDS = ("saleStartTime", "lotterySaleBeginTime")


def pool_time(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        return (
            dt.replace(tzinfo=business_timezone())
            if dt.tzinfo is None
            else dt.astimezone(business_timezone())
        )
    except ValueError, TypeError, OverflowError:
        return None


def sale_window(raw: dict, *, now: datetime | None = None) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    current = business_now(now)
    stop_key = next((k for k in STOP_FIELDS if raw.get(k)), None)
    start_key = next((k for k in START_FIELDS if raw.get(k)), None)
    stop = pool_time(raw.get(stop_key)) if stop_key else None
    start = pool_time(raw.get(start_key)) if start_key else None
    stops = {pool_time(raw[k]) for k in STOP_FIELDS if raw.get(k)}
    starts = {pool_time(raw[k]) for k in START_FIELDS if raw.get(k)}
    state = "unknown"
    flag = raw.get("onSale")
    if stop is not None:
        if stop <= current:
            state = "closed"
        elif start is not None and current < start:
            state = "not_started"
        else:
            state = "selling"
        if flag in (0, False) and state == "selling":
            state = "suspended"
        elif flag in (1, True) and state != "selling":
            state = "conflict"
    if (
        len(stops) > 1
        or len(starts) > 1
        or (None in stops)
        or (None in starts)
        or (start and stop and start >= stop)
    ):
        state = "conflict"
    return {
        "state": state,
        "sale_start": start.isoformat() if start else None,
        "sale_stop": stop.isoformat() if stop else None,
        "sale_stop_source": stop_key,
        "sale_start_source": start_key,
    }
