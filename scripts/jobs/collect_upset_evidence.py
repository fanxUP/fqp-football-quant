"""Scheduled cold-result evidence collection."""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.upset.review_storage import collect_evidence


def run(limit: int = 500) -> dict[str, Any]:
    with get_db() as conn:
        return collect_evidence(conn, limit=limit)


if __name__ == "__main__":
    print(run())
