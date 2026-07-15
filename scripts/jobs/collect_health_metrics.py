"""Operational health metrics collection job.

Stage 8: Daily job (23:55) that computes all 7 Stage 8 KPIs:
  1. Continuous uptime (days since last restart)
  2. Official collection success rate (target >= 98%)
  3. Odds snapshot missing rate (target <= 2%)
  4. Review generation success rate (target >= 99%)
  5. Backup success rate (target = 100%)
  6. Evidence chain completeness (target = 100%)
  7. Data contamination count (target = 0)

Stores results in operational_health_snapshots for dashboard and alerting.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, date, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.business_time import business_today
from scripts.local.scheduler_heartbeat import is_scheduler_alive
from scripts.local.service_health import is_http_service_alive
from scripts.local.worker_heartbeat import is_worker_alive
from scripts.ops_storage import (
    get_backup_success_rate,
    get_contamination_stats,
    get_evidence_chain_stats,
    store_health_snapshot,
)


def _now() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


def _compute_official_collection_rate(conn: Any, business_date: date | None = None) -> dict:
    """Compute official data collection success rate for today."""
    today = business_date or business_today()
    with conn.cursor() as cur:
        # Count matches in Selling status that should have been collected
        cur.execute(
            """
            SELECT COUNT(*) FROM official_matches
            WHERE sale_status = 'selling'
              AND DATE(kickoff_time) >= %(today)s
            """,
            {"today": today},
        )
        total = cur.fetchone()[0] or 0

        # Count successfully collected (have odds snapshots)
        cur.execute(
            """
            SELECT COUNT(DISTINCT m.id) FROM official_matches m
            JOIN official_odds_snapshots os ON os.match_id = m.id
            WHERE m.sale_status = 'selling'
              AND DATE(m.kickoff_time) >= %(today)s
            """,
            {"today": today},
        )
        collected = cur.fetchone()[0] or 0

    rate = round(collected / total, 4) if total > 0 else 1.0
    return {
        "total_official_matches": total,
        "successful_official_collections": collected,
        "rate": rate,
    }


def _compute_odds_missing_rate(conn: Any) -> dict:
    """Compute odds snapshot missing rate.

    An odds snapshot is "missing" if a Selling match has no snapshot
    within 45 minutes, allowing a 15-minute grace over the 30-minute policy.
    """
    with conn.cursor() as cur:
        # Total expected snapshots (one per Selling match)
        cur.execute(
            """SELECT COUNT(*) FROM official_matches
               WHERE sale_status = 'selling'
                 AND kickoff_time > timezone('Asia/Shanghai', NOW())"""
        )
        total = cur.fetchone()[0] or 0

        # Missing: matches outside the 30-minute policy plus 15-minute grace.
        cur.execute(
            """
            SELECT COUNT(*) FROM official_matches m
            WHERE m.sale_status = 'selling'
              AND m.kickoff_time > timezone('Asia/Shanghai', NOW())
              AND NOT EXISTS (
                SELECT 1 FROM official_odds_snapshots os
                WHERE os.match_id = m.id
                  AND os.snapshot_time >= NOW() - INTERVAL '45 minutes'
              )
            """
        )
        missing = cur.fetchone()[0] or 0

    rate = round(missing / total, 4) if total > 0 else 0.0
    return {
        "total_odds_snapshots_expected": total,
        "missing_odds_snapshots": missing,
        "rate": rate,
    }


def _compute_review_generation_rate(conn: Any) -> dict:
    """Compute daily review generation success rate."""
    with conn.cursor() as cur:
        # Successful: reviews with content (not empty/error)
        cur.execute(
            """
            SELECT COUNT(*) FROM daily_reviews
            WHERE created_at >= CURRENT_DATE - INTERVAL '30 days'
              AND summary_text IS NOT NULL
              AND summary_text != ''
            """
        )
        success = cur.fetchone()[0] or 0

        # Find the earliest review date to calculate expected days
        cur.execute("SELECT MIN(review_date) FROM daily_reviews")
        earliest = cur.fetchone()[0]
        if earliest:
            days_running = (business_today() - earliest).days + 1
        else:
            days_running = 1
    # Expected = days since first review, capped at 30 and minimum 1
    expected = max(1, min(30, days_running))
    rate = round(success / expected, 4) if expected > 0 else 0.0
    return {
        "total_reviews_expected": expected,
        "successful_review_generations": success,
        "rate": min(rate, 1.0),
    }


def _compute_uptime_days(
    conn: Any,
    business_date: date,
    services: dict[str, bool],
) -> int:
    """Count consecutive healthy calendar dates without same-day inflation."""
    if not all(services.values()):
        return 0
    with conn.cursor() as cur:
        cur.execute(
            """SELECT snapshot_date, scheduler_running, worker_running,
                      api_responding, db_responding
               FROM operational_health_snapshots
               WHERE snapshot_date < %s
                 AND snapshot_date >= %s - INTERVAL '366 days'
               ORDER BY snapshot_date DESC""",
            (business_date, business_date),
        )
        rows = cur.fetchall()

    healthy_dates = {row[0] for row in rows if all(bool(value) for value in row[1:5])}
    uptime_days = 1
    expected_date = business_date - timedelta(days=1)
    while expected_date in healthy_dates:
        uptime_days += 1
        expected_date -= timedelta(days=1)
    return uptime_days


def _check_system_services(conn: Any) -> dict:
    """Check if core services are responding."""
    return {
        "scheduler_running": is_scheduler_alive(),
        "worker_running": is_worker_alive(),
        "api_responding": is_http_service_alive(),
        "db_responding": True,
    }


def _get_disk_usage() -> float | None:
    """Get disk usage percentage for the data directory."""
    data_dir = os.environ.get("FQP_DATA_DIR", "./data")
    for path in (data_dir, "/"):
        try:
            usage = shutil.disk_usage(path)
            return round((usage.used / usage.total) * 100, 2)
        except OSError:
            continue
    return None


def run(dry_run: bool = False) -> dict[str, Any]:
    """Collect operational health metrics for today.

    Computes all 7 Stage 8 KPIs and stores a health snapshot.

    Returns:
        Summary dict with all computed metrics.
    """
    snap_time = _now()
    today = business_today()

    with get_db() as conn:
        # 1. Official collection success rate
        official = _compute_official_collection_rate(conn, today)

        # 2. Odds snapshot missing rate
        odds_missing = _compute_odds_missing_rate(conn)

        # 3. Review generation success rate
        reviews = _compute_review_generation_rate(conn)

        # 4. Backup success rate (last 30 days)
        backups = get_backup_success_rate(conn, days=30)

        # 5. Evidence chain completeness
        evidence = get_evidence_chain_stats(conn, days=30)

        # 6. Data contamination
        contamination = get_contamination_stats(conn, days=30)

        # System services
        services = _check_system_services(conn)

        # 7. Uptime
        uptime_days = _compute_uptime_days(conn, today, services)

        # Disk usage
        disk_pct = _get_disk_usage()

        # Determine overall health status
        official_ok = official["rate"] >= 0.98
        odds_ok = odds_missing["rate"] <= 0.02
        reviews_ok = reviews["rate"] >= 0.99
        backup_ok = backups["success_rate"] >= 1.0
        evidence_ok = bool(
            evidence["has_data"]
            and evidence["completeness_rate"] is not None
            and evidence["completeness_rate"] >= 1.0
        )
        contamination_ok = bool(
            contamination["has_data"] and contamination["contamination_found"] == 0
        )

        services_ok = all(services.values())
        all_ok = all(
            [
                official_ok,
                odds_ok,
                reviews_ok,
                backup_ok,
                evidence_ok,
                contamination_ok,
                services_ok,
            ]
        )
        any_critical = not official_ok or contamination["critical_found"] > 0 or not services_ok

        if all_ok:
            overall = "healthy"
            notes = "All Stage 8 metrics within targets."
        elif any_critical:
            overall = "critical"
            notes_parts = []
            if not official_ok:
                notes_parts.append(f"官方采集率 {official['rate']:.1%} < 98%")
            if contamination["critical_found"] > 0:
                notes_parts.append(f"数据污染 {contamination['critical_found']} 条")
            offline_services = [
                label
                for key, label in {
                    "scheduler_running": "Scheduler",
                    "worker_running": "Worker",
                    "api_responding": "API",
                    "db_responding": "数据库",
                }.items()
                if not services[key]
            ]
            if offline_services:
                notes_parts.append("服务中断: " + ", ".join(offline_services))
            notes = "; ".join(notes_parts)
        else:
            overall = "degraded"
            notes_parts = []
            if not odds_ok:
                notes_parts.append(f"赔率缺失率 {odds_missing['rate']:.1%} > 2%")
            if not reviews_ok:
                notes_parts.append(f"日报成功率 {reviews['rate']:.1%} < 99%")
            if not backup_ok:
                notes_parts.append(f"备份成功率 {backups['success_rate']:.1%} < 100%")
            if not evidence_ok:
                if evidence["has_data"] and evidence["completeness_rate"] is not None:
                    notes_parts.append(f"证据链完整率 {evidence['completeness_rate']:.1%} < 100%")
                else:
                    notes_parts.append("证据链暂无审计样本")
            if not contamination_ok and not contamination["has_data"]:
                notes_parts.append("污染审计暂无样本")
            elif not contamination_ok:
                notes_parts.append(f"数据污染 {contamination['contamination_found']} 条待处理")
            notes = "; ".join(notes_parts) if notes_parts else "Some metrics below target."

        contamination_count = (
            contamination["contamination_found"] if contamination["has_data"] else None
        )

        # Assemble snapshot
        snapshot = {
            "snapshot_date": today.isoformat(),
            "snapshot_time": snap_time,
            "continuous_uptime_days": uptime_days,
            "official_collection_success_rate": official["rate"],
            "odds_snapshot_missing_rate": odds_missing["rate"],
            "review_generation_success_rate": reviews["rate"],
            "backup_success": backups["success_rate"] >= 1.0,
            "evidence_chain_completeness_rate": evidence["completeness_rate"],
            "data_contamination_count": contamination_count,
            "total_official_matches": official["total_official_matches"],
            "successful_official_collections": official["successful_official_collections"],
            "total_odds_snapshots_expected": odds_missing["total_odds_snapshots_expected"],
            "missing_odds_snapshots": odds_missing["missing_odds_snapshots"],
            "total_reviews_expected": reviews["total_reviews_expected"],
            "successful_review_generations": reviews["successful_review_generations"],
            "total_recommendations": evidence["unique_recommendations"],
            "recommendations_with_full_chain": evidence["complete_chains"],
            "contamination_issues_found": contamination["contamination_found"],
            "scheduler_running": services["scheduler_running"],
            "worker_running": services["worker_running"],
            "api_responding": services["api_responding"],
            "db_responding": services["db_responding"],
            "disk_usage_pct": disk_pct,
            "last_backup_at": None,  # populated by backup job
            "overall_health_status": overall,
            "health_notes": notes,
            "raw_details": {
                "official": official,
                "odds_missing": odds_missing,
                "reviews": reviews,
                "backups": backups,
                "evidence": evidence,
                "contamination": contamination,
                "services": services,
            },
        }

        if not dry_run:
            store_health_snapshot(conn, snapshot)

    return {
        "status": "ok" if not dry_run else "dry_run",
        "overall_health": overall,
        "metrics": {
            "official_collection_rate": official["rate"],
            "odds_missing_rate": odds_missing["rate"],
            "review_generation_rate": reviews["rate"],
            "backup_success_rate": backups["success_rate"],
            "evidence_chain_completeness": evidence["completeness_rate"],
            "data_contamination_count": contamination_count,
            "uptime_days": uptime_days,
            "disk_usage_pct": disk_pct,
        },
        "notes": notes,
    }


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
