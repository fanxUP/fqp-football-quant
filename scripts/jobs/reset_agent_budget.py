"""Daily agent budget reset job.

Runs at 23:59 daily. Resets the competition_agent bankroll account
balance back to ¥500. Records a daily_budget_reset transaction.

Unused funds from the day DO NOT carry over — the agent gets a fresh
¥500 each day.
"""

from __future__ import annotations

from typing import Any

from apps.backend.src.db import get_db
from scripts.competition_storage import reset_agent_budget


def run(dry_run: bool = False) -> dict[str, Any]:
    """Reset the agent competition bankroll to ¥500."""
    if dry_run:
        return {"status": "dry_run", "message": "agent budget reset (dry run)"}

    with get_db() as conn:
        result = reset_agent_budget(conn)

    return result
