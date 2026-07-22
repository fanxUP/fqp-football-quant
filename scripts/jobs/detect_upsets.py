"""Scheduled entrypoint for official closing-odds upset detection."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.backend.src.db import get_db
from scripts.upset.storage import detect_and_store


def run(business_date: date | None = None, limit: int = 500) -> dict[str, Any]:
    with get_db() as conn:
        return detect_and_store(conn, business_date=business_date, limit=limit)


if __name__ == "__main__":
    print(run())
