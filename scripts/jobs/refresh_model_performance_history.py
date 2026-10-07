"""Maintain the compact settled-pick table used by the model history chart."""

from __future__ import annotations

from apps.backend.src.db import get_db
from scripts.model_performance import refresh_model_performance_scored_picks


def run() -> dict[str, object]:
    """Backfill once, refresh recent changes, and reconcile the full window weekly."""
    with get_db() as conn:
        result = refresh_model_performance_scored_picks(conn)
    print(f"[refresh_model_performance_history] {result}")
    return result


if __name__ == "__main__":
    result = run()
    if result["status"] not in ("ok", "skipped"):
        import sys

        sys.exit(1)
