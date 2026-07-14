"""Persistence for the Agent's daily buy-or-abstain decision."""

from __future__ import annotations

from datetime import date
from typing import Any

from scripts.competition_storage import AGENT_DAILY_BUDGET

DECISION_STATUSES = {"purchased", "abstained", "failed"}


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def upsert_agent_daily_decision(
    conn: Any,
    decision_date: date,
    status: str,
    total_stake: float,
    reason: str,
) -> None:
    """Store a single auditable decision for the business date."""
    if status not in DECISION_STATUSES:
        raise ValueError(f"unsupported decision status: {status}")
    stake = max(0.0, min(float(total_stake), AGENT_DAILY_BUDGET))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_budget_plans (
                plan_date, total_budget, suggested_stake, unused_budget,
                risk_mode, reason, status, created_at, updated_at
            ) VALUES (
                %(decision_date)s, %(total_budget)s, %(total_stake)s, %(unused_budget)s,
                'balanced', %(reason)s, %(status)s, now(), now()
            )
            ON CONFLICT (plan_date) DO UPDATE SET
                total_budget = EXCLUDED.total_budget,
                suggested_stake = EXCLUDED.suggested_stake,
                unused_budget = EXCLUDED.unused_budget,
                reason = EXCLUDED.reason,
                status = EXCLUDED.status,
                updated_at = now()
            """,
            {
                "decision_date": decision_date,
                "total_budget": AGENT_DAILY_BUDGET,
                "total_stake": stake,
                "unused_budget": AGENT_DAILY_BUDGET - stake,
                "reason": reason[:1000],
                "status": status,
            },
        )
    conn.commit()


def list_agent_daily_decisions(conn: Any, limit: int = 14) -> list[dict[str, Any]]:
    """Return recent terminal decisions, newest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT plan_date, total_budget, suggested_stake, unused_budget,
                   status, reason, updated_at
            FROM daily_budget_plans
            WHERE status IN ('purchased', 'abstained', 'failed')
            ORDER BY plan_date DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        rows = cur.fetchall()
    return [
        {
            "decisionDate": _iso(row[0]),
            "status": row[4],
            "totalBudget": float(row[1] or 0),
            "totalStake": float(row[2] or 0),
            "unusedBudget": float(row[3] or 0),
            "reason": row[5] or "",
            "updatedAt": _iso(row[6]),
        }
        for row in rows
    ]
