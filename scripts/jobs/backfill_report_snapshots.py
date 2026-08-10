"""Auditable one-time upgrade of completed report snapshots to schema v4."""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from apps.backend.src.db import get_db
from apps.backend.src.services.match_review import build_match_review_cards
from apps.backend.src.services.report_performance import build_periodic_performance
from apps.backend.src.services.report_snapshot import (
    build_daily_report_snapshot,
    build_periodic_research_breakdowns,
    build_periodic_research_metrics,
)
from scripts.jobs.generate_periodic_reviews import _load_completed_daily_snapshots
from scripts.jobs.report_generation import replace_completed_report_snapshot_with_revision

BACKFILL_REASON = "升级真实赛果评价与证据复盘"


def _snapshot(value: Any) -> dict[str, Any]:
    parsed = json.loads(value) if isinstance(value, str) else value
    return dict(parsed) if isinstance(parsed, dict) else {}


def build_daily_backfill_snapshot(
    period_key: str,
    previous: dict[str, Any],
    match_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    """Rebuild one daily derivative while retaining its original source facts."""
    cards = match_cards or list(previous.get("matches") or [])
    upgraded = build_daily_report_snapshot(
        review=previous.get("dailyReview") or {"reviewDate": period_key},
        upset_report=previous.get("upsetReport") or {},
        match_cards=cards,
    )
    upgraded["backfill"] = {
        "reason": BACKFILL_REASON,
        "supersedesSchemaVersion": int(previous.get("schemaVersion") or 1),
        "interpretationRequiresRefresh": True,
    }
    return upgraded


def build_periodic_backfill_snapshot(
    previous: dict[str, Any],
    daily_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    """Upgrade a period exclusively from its now-versioned daily snapshots."""
    upgraded = {
        **previous,
        "schemaVersion": 4,
        "researchMetrics": build_periodic_research_metrics(daily_snapshots),
        "researchBreakdowns": build_periodic_research_breakdowns(daily_snapshots),
        **build_periodic_performance(daily_snapshots),
        "dailyReportRefs": [snapshot["periodKey"] for snapshot in daily_snapshots],
        "backfill": {
            "reason": BACKFILL_REASON,
            "supersedesSchemaVersion": int(previous.get("schemaVersion") or 1),
            "interpretationRequiresRefresh": True,
        },
    }
    return upgraded


def _period_bounds(report_type: str, period_key: str, snapshot: dict[str, Any]) -> tuple[str, str]:
    if report_type == "weekly":
        start = str(snapshot.get("weekStart") or period_key)
        end = str(snapshot.get("weekEnd") or (date.fromisoformat(start) + timedelta(days=6)))
        return start, end
    start = f"{period_key}-01"
    end = (date.fromisoformat(start).replace(day=28) + timedelta(days=4)).replace(
        day=1
    ) - timedelta(days=1)
    return start, end.isoformat()


def run(*, limit: int = 100, dry_run: bool = False) -> dict[str, Any]:
    """Upgrade completed reports, preserving every superseded snapshot revision."""
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT report_type, period_key, source_snapshot_json
                   FROM report_generation_runs
                   WHERE status = 'completed'
                     AND COALESCE((source_snapshot_json->>'schemaVersion')::int, 1) < 4
                   ORDER BY CASE report_type WHEN 'daily' THEN 0 ELSE 1 END,
                            period_key ASC
                   LIMIT %s""",
                (limit,),
            )
            pending = [(str(row[0]), str(row[1]), _snapshot(row[2])) for row in cur.fetchall()]

        if dry_run:
            return {
                "status": "dry_run",
                "pending": len(pending),
                "sources": [f"{kind}:{key}" for kind, key, _snapshot_value in pending],
            }

        upgraded_daily = 0
        upgraded_periodic = 0
        revisions: list[dict[str, Any]] = []
        for report_type, period_key, previous in pending:
            if report_type != "daily":
                continue
            upgraded = build_daily_backfill_snapshot(
                period_key,
                previous,
                build_match_review_cards(conn, period_key),
            )
            revisions.append(
                replace_completed_report_snapshot_with_revision(
                    conn,
                    report_type="daily",
                    period_key=period_key,
                    snapshot=upgraded,
                    reason=BACKFILL_REASON,
                )
            )
            upgraded_daily += 1

        for report_type, period_key, previous in pending:
            if report_type == "daily":
                continue
            start, end = _period_bounds(report_type, period_key, previous)
            daily_snapshots = _load_completed_daily_snapshots(conn, start, end)
            upgraded = build_periodic_backfill_snapshot(previous, daily_snapshots)
            revisions.append(
                replace_completed_report_snapshot_with_revision(
                    conn,
                    report_type=report_type,
                    period_key=period_key,
                    snapshot=upgraded,
                    reason=BACKFILL_REASON,
                )
            )
            upgraded_periodic += 1

    return {
        "status": "ok",
        "upgradedDaily": upgraded_daily,
        "upgradedPeriodic": upgraded_periodic,
        "revisions": revisions,
    }


if __name__ == "__main__":
    import sys

    print(run(dry_run="--dry-run" in sys.argv))
