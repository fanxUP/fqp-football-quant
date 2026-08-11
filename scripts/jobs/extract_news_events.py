"""Build structured news events without affecting prediction or betting chains."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.news_event_storage import process_pending_news_articles


def run(limit: int = 200) -> dict[str, Any]:
    with get_db() as conn:
        return process_pending_news_articles(conn, limit=limit)


if __name__ == "__main__":
    print(run())
