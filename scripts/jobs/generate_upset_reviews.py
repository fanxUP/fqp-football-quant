"""Scheduled evidence-grounded cold-result reviews."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.upset.review_storage import generate_reviews


def run(limit: int = 500) -> dict[str, Any]:
    with get_db() as conn:
        return generate_reviews(conn, limit=limit)


if __name__ == "__main__":
    print(run())
