"""Canonical Asia/Shanghai business clock for jobs and API date boundaries."""

from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo


def business_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("FQP_TIMEZONE", "Asia/Shanghai"))


def business_now(value: datetime | None = None) -> datetime:
    """Return an aware datetime in the configured business timezone."""
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(business_timezone())


def business_today(value: datetime | None = None) -> date:
    return business_now(value).date()


def business_yesterday(value: datetime | None = None) -> date:
    return business_today(value) - timedelta(days=1)
