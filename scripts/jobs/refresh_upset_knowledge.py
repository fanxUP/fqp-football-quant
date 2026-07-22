"""Refresh time-bounded cold-result research knowledge profiles."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_today
from scripts.upset.knowledge import refresh_knowledge


def run(end: date | None = None, window_days: int = 180) -> dict[str, Any]:
    with get_db() as conn:
        return refresh_knowledge(
            conn,
            end=end or business_today(),
            window_days=window_days,
        )


if __name__ == "__main__":
    print(run())
