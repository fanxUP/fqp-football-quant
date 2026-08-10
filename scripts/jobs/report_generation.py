"""Readiness and immutable run storage for automated review reports.

This module deliberately reads only official results and ticket settlement
state.  It never writes predictions, recommendations, risk decisions, or
ticket business facts.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

from scripts.business_time import business_now

POST_MATCH_WINDOW = timedelta(hours=4)


def _business_now_naive(now: datetime | None) -> datetime:
    """Use Asia/Shanghai for live runs while keeping unit-test inputs intuitive."""
    if now is not None and now.tzinfo is None:
        return now
    return business_now(now).replace(tzinfo=None)


def assess_daily_report_readiness(
    conn: Any,
    review_date: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return whether a daily report has complete official and settlement facts."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS official_match_count,
                   COUNT(*) FILTER (
                     WHERE result.result_status IN ('confirmed', 'void', 'refund', 'refunded')
                   ) AS confirmed_result_count,
                   MAX(match.kickoff_time) AS latest_kickoff_time
            FROM official_matches match
            LEFT JOIN official_results result ON result.match_id = match.id
            WHERE match.business_date = %s
            """,
            (review_date,),
        )
        official_match_count, confirmed_result_count, latest_kickoff_time = cur.fetchone()

        cur.execute(
            """
            WITH relevant_tickets AS (
                SELECT 'simulation'::text AS ticket_source, ticket.id AS ticket_id
                FROM simulation_tickets ticket
                JOIN simulation_ticket_items item ON item.ticket_id = ticket.id
                JOIN official_matches match ON match.id = item.match_id
                WHERE match.business_date = %s
                  AND ticket.ticket_status IN ('generated', 'activated', 'settled')
                GROUP BY ticket.id
                UNION
                SELECT 'real'::text AS ticket_source, ticket.id AS ticket_id
                FROM real_tickets ticket
                JOIN real_ticket_items item ON item.real_ticket_id = ticket.id
                JOIN official_matches match ON match.id = item.match_id
                WHERE match.business_date = %s
                  AND ticket.confirm_status = 'confirmed'
                GROUP BY ticket.id
            )
            SELECT COUNT(*) AS unsettled_ticket_count
            FROM relevant_tickets relevant
            WHERE NOT EXISTS (
                SELECT 1
                FROM ticket_settlements settlement
                WHERE settlement.ticket_source = relevant.ticket_source
                  AND settlement.ticket_id = relevant.ticket_id
            )
            """,
            (review_date, review_date),
        )
        unsettled_ticket_count = cur.fetchone()[0]

    total = int(official_match_count or 0)
    confirmed = int(confirmed_result_count or 0)
    unsettled = int(unsettled_ticket_count or 0)
    if total == 0:
        return {
            "canGenerate": False,
            "status": "skipped",
            "reasonCodes": ["NO_OFFICIAL_MATCHES"],
            "officialMatchCount": 0,
            "confirmedResultCount": 0,
            "unsettledTicketCount": 0,
            "latestKickoffTime": None,
            "eligibleAt": None,
        }

    eligible_at = latest_kickoff_time + POST_MATCH_WINDOW if latest_kickoff_time else None
    reason_codes: list[str] = []
    if confirmed < total:
        reason_codes.append("OFFICIAL_RESULT_PENDING")
    if unsettled:
        reason_codes.append("TICKET_SETTLEMENT_PENDING")
    if eligible_at and _business_now_naive(now) < eligible_at:
        reason_codes.append("POST_MATCH_WINDOW_OPEN")

    return {
        "canGenerate": not reason_codes,
        "status": "ready" if not reason_codes else "waiting",
        "reasonCodes": reason_codes,
        "officialMatchCount": total,
        "confirmedResultCount": confirmed,
        "unsettledTicketCount": unsettled,
        "latestKickoffTime": latest_kickoff_time.isoformat() if latest_kickoff_time else None,
        "eligibleAt": eligible_at.isoformat() if eligible_at else None,
    }


def assess_periodic_report_readiness(
    conn: Any,
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Require a completed daily report for every official-match day in a period."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH official_days AS (
                SELECT DISTINCT business_date
                FROM official_matches
                WHERE business_date BETWEEN %s AND %s
            ), completed_daily_runs AS (
                SELECT period_key::date AS review_date
                FROM report_generation_runs
                WHERE report_type = 'daily' AND status = 'completed'
            )
            SELECT COUNT(*) AS official_day_count,
                   COUNT(completed.review_date) AS completed_daily_report_count,
                   COALESCE(
                       array_agg(official.business_date::text ORDER BY official.business_date)
                       FILTER (WHERE completed.review_date IS NULL),
                       ARRAY[]::text[]
                   ) AS pending_daily_report_dates
            FROM official_days official
            LEFT JOIN completed_daily_runs completed
              ON completed.review_date = official.business_date
            """,
            (start, end),
        )
        official_day_count, completed_daily_report_count, pending_dates = cur.fetchone()

    total = int(official_day_count or 0)
    completed = int(completed_daily_report_count or 0)
    pending = [str(value) for value in (pending_dates or [])]
    if total == 0:
        return {
            "canGenerate": False,
            "status": "skipped",
            "reasonCodes": ["NO_OFFICIAL_MATCHES"],
            "officialDayCount": 0,
            "completedDailyReportCount": 0,
            "pendingDailyReportDates": [],
            "periodStart": start,
            "periodEnd": end,
        }

    return {
        "canGenerate": completed == total,
        "status": "ready" if completed == total else "waiting",
        "reasonCodes": [] if completed == total else ["DAILY_REPORT_PENDING"],
        "officialDayCount": total,
        "completedDailyReportCount": completed,
        "pendingDailyReportDates": pending,
        "periodStart": start,
        "periodEnd": end,
    }


def has_completed_report_generation_run(
    conn: Any,
    *,
    report_type: str,
    period_key: str,
) -> bool:
    """Keep an automatically completed period immutable on later scheduler checks."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM report_generation_runs
                WHERE report_type = %s AND period_key = %s AND status = 'completed'
            )
            """,
            (report_type, period_key),
        )
        return bool(cur.fetchone()[0])


def upsert_report_generation_run(
    conn: Any,
    *,
    report_type: str,
    period_key: str,
    status: str,
    readiness: dict[str, Any],
    snapshot: dict[str, Any] | None = None,
) -> None:
    """Persist a traceable report lifecycle record without altering business facts."""
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True)
    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest() if snapshot else None
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO report_generation_runs (
                report_type, period_key, status, readiness_json, source_snapshot_json,
                source_snapshot_hash, completed_at, updated_at
            ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s,
                      CASE WHEN %s = 'completed' THEN now() ELSE NULL END, now())
            ON CONFLICT (report_type, period_key) DO UPDATE SET
                status = EXCLUDED.status,
                readiness_json = EXCLUDED.readiness_json,
                source_snapshot_json = CASE
                    WHEN EXCLUDED.source_snapshot_json = '{}'::jsonb
                    THEN report_generation_runs.source_snapshot_json
                    ELSE EXCLUDED.source_snapshot_json
                END,
                source_snapshot_hash = COALESCE(
                    EXCLUDED.source_snapshot_hash, report_generation_runs.source_snapshot_hash
                ),
                completed_at = COALESCE(EXCLUDED.completed_at, report_generation_runs.completed_at),
                updated_at = now()
            """,
            (
                report_type,
                period_key,
                status,
                json.dumps(readiness, ensure_ascii=False, default=str),
                snapshot_json,
                snapshot_hash,
                status,
            ),
        )
    conn.commit()


def replace_completed_report_snapshot_with_revision(
    conn: Any,
    *,
    report_type: str,
    period_key: str,
    snapshot: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """Archive the current immutable snapshot before a traceable backfill.

    The business review row and every prediction, ticket, settlement and risk
    fact remain untouched.  Only the derived report snapshot is superseded.
    """
    snapshot_json = json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True)
    snapshot_hash = hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """SELECT source_snapshot_json, source_snapshot_hash
               FROM report_generation_runs
               WHERE report_type = %s AND period_key = %s AND status = 'completed'
               FOR UPDATE""",
            (report_type, period_key),
        )
        current = cur.fetchone()
        if not current:
            raise ValueError("找不到已完成的自动报告快照")
        previous_snapshot, previous_hash = current
        cur.execute(
            """SELECT COALESCE(MAX(revision), 0) + 1
               FROM report_generation_revisions
               WHERE report_type = %s AND period_key = %s""",
            (report_type, period_key),
        )
        revision = int(cur.fetchone()[0])
        cur.execute(
            """INSERT INTO report_generation_revisions (
                   report_type, period_key, revision, previous_snapshot_json,
                   previous_snapshot_hash, replacement_snapshot_hash, reason
               ) VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)""",
            (
                report_type,
                period_key,
                revision,
                json.dumps(previous_snapshot, ensure_ascii=False, default=str),
                previous_hash,
                snapshot_hash,
                reason,
            ),
        )
        cur.execute(
            """UPDATE report_generation_runs
               SET source_snapshot_json = %s::jsonb,
                   source_snapshot_hash = %s,
                   updated_at = now()
               WHERE report_type = %s AND period_key = %s AND status = 'completed'""",
            (snapshot_json, snapshot_hash, report_type, period_key),
        )
    conn.commit()
    return {
        "reportType": report_type,
        "periodKey": period_key,
        "revision": revision,
        "previousSnapshotHash": previous_hash,
        "snapshotHash": snapshot_hash,
    }
