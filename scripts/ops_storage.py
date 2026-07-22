"""Operational health storage layer.

Stage 8: CRUD for operational monitoring tables:
  - operational_health_snapshots
  - backup_logs
  - evidence_chain_audit_logs
  - data_contamination_audit_logs

Follows the same psycopg2 pattern as scripts/official_storage.py and
scripts/feature_storage.py.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from scripts.business_time import utc_now_iso

# ---------------------------------------------------------------------------
# operational_health_snapshots
# ---------------------------------------------------------------------------


def store_health_snapshot(conn: Any, snapshot: dict) -> int | None:
    """Insert or update a daily operational health snapshot.

    Unique key: snapshot_date.
    Returns the snapshot id.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM operational_health_snapshots WHERE snapshot_date = %(snapshot_date)s",
            {"snapshot_date": snapshot["snapshot_date"]},
        )
        row = cur.fetchone()

        common = {
            "snapshot_date": snapshot["snapshot_date"],
            "snapshot_time": snapshot.get("snapshot_time", utc_now_iso()),
            "continuous_uptime_days": snapshot.get("continuous_uptime_days"),
            "official_collection_success_rate": snapshot.get("official_collection_success_rate"),
            "odds_snapshot_missing_rate": snapshot.get("odds_snapshot_missing_rate"),
            "review_generation_success_rate": snapshot.get("review_generation_success_rate"),
            "backup_success": snapshot.get("backup_success"),
            "evidence_chain_completeness_rate": snapshot.get("evidence_chain_completeness_rate"),
            "data_contamination_count": snapshot.get("data_contamination_count", 0),
            "total_official_matches": snapshot.get("total_official_matches"),
            "successful_official_collections": snapshot.get("successful_official_collections"),
            "total_odds_snapshots_expected": snapshot.get("total_odds_snapshots_expected"),
            "missing_odds_snapshots": snapshot.get("missing_odds_snapshots"),
            "total_reviews_expected": snapshot.get("total_reviews_expected"),
            "successful_review_generations": snapshot.get("successful_review_generations"),
            "total_recommendations": snapshot.get("total_recommendations"),
            "recommendations_with_full_chain": snapshot.get("recommendations_with_full_chain"),
            "contamination_issues_found": snapshot.get("contamination_issues_found"),
            "scheduler_running": snapshot.get("scheduler_running"),
            "worker_running": snapshot.get("worker_running"),
            "api_responding": snapshot.get("api_responding"),
            "db_responding": snapshot.get("db_responding"),
            "disk_usage_pct": snapshot.get("disk_usage_pct"),
            "last_backup_at": snapshot.get("last_backup_at"),
            "overall_health_status": snapshot.get("overall_health_status", "degraded"),
            "health_notes": snapshot.get("health_notes"),
            "raw_details": json.dumps(snapshot.get("raw_details", {}), ensure_ascii=False),
        }

        if row:
            cur.execute(
                """
                UPDATE operational_health_snapshots SET
                    snapshot_time = %(snapshot_time)s,
                    continuous_uptime_days = %(continuous_uptime_days)s,
                    official_collection_success_rate = %(official_collection_success_rate)s,
                    odds_snapshot_missing_rate = %(odds_snapshot_missing_rate)s,
                    review_generation_success_rate = %(review_generation_success_rate)s,
                    backup_success = %(backup_success)s,
                    evidence_chain_completeness_rate = %(evidence_chain_completeness_rate)s,
                    data_contamination_count = %(data_contamination_count)s,
                    total_official_matches = %(total_official_matches)s,
                    successful_official_collections = %(successful_official_collections)s,
                    total_odds_snapshots_expected = %(total_odds_snapshots_expected)s,
                    missing_odds_snapshots = %(missing_odds_snapshots)s,
                    total_reviews_expected = %(total_reviews_expected)s,
                    successful_review_generations = %(successful_review_generations)s,
                    total_recommendations = %(total_recommendations)s,
                    recommendations_with_full_chain = %(recommendations_with_full_chain)s,
                    contamination_issues_found = %(contamination_issues_found)s,
                    scheduler_running = %(scheduler_running)s,
                    worker_running = %(worker_running)s,
                    api_responding = %(api_responding)s,
                    db_responding = %(db_responding)s,
                    disk_usage_pct = %(disk_usage_pct)s,
                    last_backup_at = %(last_backup_at)s,
                    overall_health_status = %(overall_health_status)s,
                    health_notes = %(health_notes)s,
                    raw_details = %(raw_details)s
                WHERE id = %(id)s
                """,
                {**common, "id": row[0]},
            )
            snap_id = row[0]
        else:
            cur.execute(
                """
                INSERT INTO operational_health_snapshots (
                    snapshot_date, snapshot_time, continuous_uptime_days,
                    official_collection_success_rate, odds_snapshot_missing_rate,
                    review_generation_success_rate, backup_success,
                    evidence_chain_completeness_rate, data_contamination_count,
                    total_official_matches, successful_official_collections,
                    total_odds_snapshots_expected, missing_odds_snapshots,
                    total_reviews_expected, successful_review_generations,
                    total_recommendations, recommendations_with_full_chain,
                    contamination_issues_found,
                    scheduler_running, worker_running, api_responding, db_responding,
                    disk_usage_pct, last_backup_at,
                    overall_health_status, health_notes, raw_details
                ) VALUES (
                    %(snapshot_date)s, %(snapshot_time)s, %(continuous_uptime_days)s,
                    %(official_collection_success_rate)s, %(odds_snapshot_missing_rate)s,
                    %(review_generation_success_rate)s, %(backup_success)s,
                    %(evidence_chain_completeness_rate)s, %(data_contamination_count)s,
                    %(total_official_matches)s, %(successful_official_collections)s,
                    %(total_odds_snapshots_expected)s, %(missing_odds_snapshots)s,
                    %(total_reviews_expected)s, %(successful_review_generations)s,
                    %(total_recommendations)s, %(recommendations_with_full_chain)s,
                    %(contamination_issues_found)s,
                    %(scheduler_running)s, %(worker_running)s, %(api_responding)s, %(db_responding)s,
                    %(disk_usage_pct)s, %(last_backup_at)s,
                    %(overall_health_status)s, %(health_notes)s, %(raw_details)s
                ) RETURNING id
                """,
                common,
            )
            snap_id = cur.fetchone()[0]

    conn.commit()
    return snap_id


def get_latest_health_snapshot(conn: Any) -> dict | None:
    """Get the most recent operational health snapshot."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT * FROM operational_health_snapshots ORDER BY snapshot_date DESC LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_dict(
        row,
        [
            "id",
            "snapshot_date",
            "snapshot_time",
            "continuous_uptime_days",
            "official_collection_success_rate",
            "odds_snapshot_missing_rate",
            "review_generation_success_rate",
            "backup_success",
            "evidence_chain_completeness_rate",
            "data_contamination_count",
            "total_official_matches",
            "successful_official_collections",
            "total_odds_snapshots_expected",
            "missing_odds_snapshots",
            "total_reviews_expected",
            "successful_review_generations",
            "total_recommendations",
            "recommendations_with_full_chain",
            "contamination_issues_found",
            "scheduler_running",
            "worker_running",
            "api_responding",
            "db_responding",
            "disk_usage_pct",
            "last_backup_at",
            "overall_health_status",
            "health_notes",
            "raw_details",
            "created_at",
        ],
    )


def get_health_history(conn: Any, days: int = 30) -> list[dict]:
    """Get health snapshots for the last N days."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM operational_health_snapshots
            WHERE snapshot_date >= CURRENT_DATE - INTERVAL '%s days'
            ORDER BY snapshot_date DESC
            """,
            (days,),
        )
        rows = cur.fetchall()
    cols = [
        "id",
        "snapshot_date",
        "snapshot_time",
        "continuous_uptime_days",
        "official_collection_success_rate",
        "odds_snapshot_missing_rate",
        "review_generation_success_rate",
        "backup_success",
        "evidence_chain_completeness_rate",
        "data_contamination_count",
        "total_official_matches",
        "successful_official_collections",
        "total_odds_snapshots_expected",
        "missing_odds_snapshots",
        "total_reviews_expected",
        "successful_review_generations",
        "total_recommendations",
        "recommendations_with_full_chain",
        "contamination_issues_found",
        "scheduler_running",
        "worker_running",
        "api_responding",
        "db_responding",
        "disk_usage_pct",
        "last_backup_at",
        "overall_health_status",
        "health_notes",
        "raw_details",
        "created_at",
    ]
    return [_row_to_dict(r, cols) for r in rows]


# ---------------------------------------------------------------------------
# backup_logs
# ---------------------------------------------------------------------------


def store_backup_log(conn: Any, log_entry: dict) -> int:
    """Insert a backup execution log entry. Returns the log id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backup_logs (
                backup_type, backup_path, backup_size_bytes,
                started_at, finished_at, success,
                integrity_check_passed, restore_test_passed,
                error_message, backup_command
            ) VALUES (
                %(backup_type)s, %(backup_path)s, %(backup_size_bytes)s,
                %(started_at)s, %(finished_at)s, %(success)s,
                %(integrity_check_passed)s, %(restore_test_passed)s,
                %(error_message)s, %(backup_command)s
            ) RETURNING id
            """,
            {
                "backup_type": log_entry.get("backup_type", "full"),
                "backup_path": log_entry.get("backup_path"),
                "backup_size_bytes": log_entry.get("backup_size_bytes"),
                "started_at": log_entry.get("started_at", utc_now_iso()),
                "finished_at": log_entry.get("finished_at"),
                "success": log_entry.get("success", False),
                "integrity_check_passed": log_entry.get("integrity_check_passed"),
                "restore_test_passed": log_entry.get("restore_test_passed"),
                "error_message": log_entry.get("error_message"),
                "backup_command": log_entry.get("backup_command"),
            },
        )
        log_id = cur.fetchone()[0]
    conn.commit()
    return log_id


def get_latest_backup_log(conn: Any) -> dict | None:
    """Get the most recent backup log entry."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM backup_logs ORDER BY started_at DESC LIMIT 1")
        row = cur.fetchone()
    if not row:
        return None
    return _row_to_dict(
        row,
        [
            "id",
            "backup_type",
            "backup_path",
            "backup_size_bytes",
            "started_at",
            "finished_at",
            "success",
            "integrity_check_passed",
            "restore_test_passed",
            "error_message",
            "backup_command",
            "created_at",
        ],
    )


def get_backup_success_rate(conn: Any, days: int = 30) -> dict:
    """Get backup success rate for the last N days."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_backups,
                SUM(CASE WHEN success THEN 1 ELSE 0 END) AS successful_backups,
                SUM(CASE WHEN integrity_check_passed THEN 1 ELSE 0 END) AS integrity_passed
            FROM backup_logs
            WHERE started_at >= CURRENT_DATE - INTERVAL '%s days'
            """,
            (days,),
        )
        row = cur.fetchone()
    total = row[0] or 0
    success = row[1] or 0
    return {
        "total_backups": total,
        "successful_backups": success,
        "integrity_passed": row[2] or 0,
        "success_rate": round(success / total, 4) if total > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# evidence_chain_audit_logs
# ---------------------------------------------------------------------------


def store_evidence_chain_audit(conn: Any, audit: dict) -> int:
    """Insert an evidence chain audit entry. Returns the audit id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evidence_chain_audit_logs (
                audit_time, recommendation_id, ticket_id,
                odds_snapshot_id, model_version_id, feature_snapshot_id, prediction_id,
                chain_complete, broken_link_at, chain_details,
                odds_snapshot_age_seconds, feature_snapshot_age_seconds,
                model_version_is_current
            ) VALUES (
                %(audit_time)s, %(recommendation_id)s, %(ticket_id)s,
                %(odds_snapshot_id)s, %(model_version_id)s, %(feature_snapshot_id)s, %(prediction_id)s,
                %(chain_complete)s, %(broken_link_at)s, %(chain_details)s,
                %(odds_snapshot_age_seconds)s, %(feature_snapshot_age_seconds)s,
                %(model_version_is_current)s
            ) RETURNING id
            """,
            {
                "audit_time": audit.get("audit_time", utc_now_iso()),
                "recommendation_id": audit.get("recommendation_id"),
                "ticket_id": audit.get("ticket_id"),
                "odds_snapshot_id": audit.get("odds_snapshot_id"),
                "model_version_id": audit.get("model_version_id"),
                "feature_snapshot_id": audit.get("feature_snapshot_id"),
                "prediction_id": audit.get("prediction_id"),
                "chain_complete": audit.get("chain_complete", False),
                "broken_link_at": audit.get("broken_link_at"),
                "chain_details": json.dumps(audit.get("chain_details", {}), ensure_ascii=False),
                "odds_snapshot_age_seconds": audit.get("odds_snapshot_age_seconds"),
                "feature_snapshot_age_seconds": audit.get("feature_snapshot_age_seconds"),
                "model_version_is_current": audit.get("model_version_is_current"),
            },
        )
        audit_id = cur.fetchone()[0]
    conn.commit()
    return audit_id


def get_evidence_chain_stats(conn: Any, days: int = 30) -> dict:
    """Get evidence chain completeness statistics."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                COUNT(*) AS total_audited,
                SUM(CASE WHEN chain_complete THEN 1 ELSE 0 END) AS complete_chains,
                COUNT(DISTINCT recommendation_id) AS unique_recommendations
            FROM evidence_chain_audit_logs
            WHERE audit_time >= CURRENT_DATE - INTERVAL '%s days'
            """,
            (days,),
        )
        row = cur.fetchone()
    total = row[0] or 0
    complete = row[1] or 0
    return {
        "total_audited": total,
        "complete_chains": complete,
        "unique_recommendations": row[2] or 0,
        "has_data": total > 0,
        "completeness_rate": round(complete / total, 4) if total > 0 else None,
    }


def get_broken_chains(conn: Any, limit: int = 50) -> list[dict]:
    """Get recent recommendations with broken evidence chains."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evidence_chain_audit_logs
            WHERE chain_complete = false
            ORDER BY audit_time DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    cols = [
        "id",
        "audit_time",
        "recommendation_id",
        "ticket_id",
        "odds_snapshot_id",
        "model_version_id",
        "feature_snapshot_id",
        "prediction_id",
        "chain_complete",
        "broken_link_at",
        "chain_details",
        "odds_snapshot_age_seconds",
        "feature_snapshot_age_seconds",
        "model_version_is_current",
        "created_at",
    ]
    return [_row_to_dict(r, cols) for r in rows]


# ---------------------------------------------------------------------------
# data_contamination_audit_logs
# ---------------------------------------------------------------------------


def store_contamination_audit(conn: Any, audit: dict) -> int:
    """Insert a data contamination audit entry. Returns the audit id."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO data_contamination_audit_logs (
                audit_time, check_type, match_id, severity,
                contamination_detected, detail, evidence, resolved, resolution_notes
            ) VALUES (
                %(audit_time)s, %(check_type)s, %(match_id)s, %(severity)s,
                %(contamination_detected)s, %(detail)s, %(evidence)s,
                %(resolved)s, %(resolution_notes)s
            ) RETURNING id
            """,
            {
                "audit_time": audit.get("audit_time", utc_now_iso()),
                "check_type": audit["check_type"],
                "match_id": audit.get("match_id"),
                "severity": audit.get("severity", "info"),
                "contamination_detected": audit.get("contamination_detected", False),
                "detail": audit.get("detail"),
                "evidence": json.dumps(audit.get("evidence", {}), ensure_ascii=False),
                "resolved": audit.get("resolved", False),
                "resolution_notes": audit.get("resolution_notes"),
            },
        )
        audit_id = cur.fetchone()[0]
    conn.commit()
    return audit_id


def get_contamination_stats(conn: Any, days: int = 30) -> dict:
    """Get data contamination audit statistics."""
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_checks AS (
                SELECT DISTINCT ON (check_type, COALESCE(match_id, -1))
                       contamination_detected, severity, resolved
                FROM data_contamination_audit_logs
                WHERE audit_time >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY check_type, COALESCE(match_id, -1), audit_time DESC, id DESC
            )
            SELECT
                COUNT(*) AS total_checks,
                SUM(CASE WHEN contamination_detected AND NOT resolved THEN 1 ELSE 0 END)
                    AS contamination_found,
                SUM(CASE WHEN severity = 'critical' AND contamination_detected AND NOT resolved
                         THEN 1 ELSE 0 END) AS critical_found
            FROM latest_checks
            """,
            (days,),
        )
        row = cur.fetchone()
    total = row[0] or 0
    return {
        "total_checks": total,
        "contamination_found": row[1] or 0,
        "critical_found": row[2] or 0,
        "has_data": total > 0,
    }


def get_recent_contamination_issues(conn: Any, limit: int = 50) -> list[dict]:
    """Get recent contamination issues detected."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM (
                SELECT DISTINCT ON (check_type, COALESCE(match_id, -1)) *
                FROM data_contamination_audit_logs
                WHERE contamination_detected = true AND NOT resolved
                ORDER BY check_type, COALESCE(match_id, -1), audit_time DESC, id DESC
            ) latest_issues
            ORDER BY audit_time DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    cols = [
        "id",
        "audit_time",
        "check_type",
        "match_id",
        "severity",
        "contamination_detected",
        "detail",
        "evidence",
        "resolved",
        "resolution_notes",
        "created_at",
    ]
    return [_row_to_dict(r, cols) for r in rows]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: tuple, columns: list[str]) -> dict:
    """Convert a DB row tuple to a dict with named columns."""
    result = {}
    for i, col in enumerate(columns):
        if i < len(row):
            val = row[i]
            # Convert datetime objects to ISO strings
            if isinstance(val, datetime):
                val = val.isoformat()
            result[col] = val
    return result
