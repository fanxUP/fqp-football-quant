"""Operational health, metrics, evidence-chain, contamination, and backup endpoints (Stage 8)."""

from __future__ import annotations

from fastapi import APIRouter, Query

from apps.backend.src.db import get_db
from scripts.ops_storage import (
    get_backup_success_rate,
    get_broken_chains,
    get_contamination_stats,
    get_evidence_chain_stats,
    get_health_history,
    get_latest_backup_log,
    get_latest_health_snapshot,
    get_recent_contamination_issues,
)

router = APIRouter(tags=["ops"])


@router.get("/api/ops/pipeline")
def get_pipeline_status():
    """Get data source health + latest job run statuses for the Data Health dashboard."""
    with get_db() as conn:
        cur = conn.cursor()

        # Data source health
        cur.execute(
            "SELECT source_name, status, last_success_time, last_failure_time, "
            "failure_count, latency_ms FROM data_source_health ORDER BY source_name"
        )
        src_cols = ["name", "status", "last_success", "last_failure", "failures", "latency_ms"]
        sources = []
        for row in cur.fetchall():
            d = dict(zip(src_cols, row, strict=False))
            d["last_success"] = str(d["last_success"]) if d["last_success"] else None
            d["last_failure"] = str(d["last_failure"]) if d["last_failure"] else None
            sources.append(d)

        # Latest job runs
        cur.execute(
            "SELECT DISTINCT ON (job_name) job_name, status, finished_at "
            "FROM ai_job_runs ORDER BY job_name, id DESC"
        )
        job_cols = ["name", "status", "finished_at"]
        jobs = []
        for row in cur.fetchall():
            d = dict(zip(job_cols, row, strict=False))
            d["finished_at"] = str(d["finished_at"]) if d["finished_at"] else None
            jobs.append(d)

    return {"sources": sources, "jobs": jobs}


@router.get("/api/ops/health")
def get_operational_health():
    """Get current operational health status (Stage 8 KPIs)."""
    with get_db() as conn:
        snapshot = get_latest_health_snapshot(conn)

    if not snapshot:
        return {
            "status": "no_data",
            "message": "No health snapshots yet. Run collect_health_metrics job first.",
            "metrics": {},
        }

    return {
        "status": snapshot.get("overall_health_status", "unknown"),
        "snapshot_date": snapshot.get("snapshot_date"),
        "metrics": {
            "uptime_days": snapshot.get("continuous_uptime_days"),
            "official_collection_rate": snapshot.get("official_collection_success_rate"),
            "odds_missing_rate": snapshot.get("odds_snapshot_missing_rate"),
            "review_generation_rate": snapshot.get("review_generation_success_rate"),
            "backup_success": snapshot.get("backup_success"),
            "evidence_chain_completeness": snapshot.get("evidence_chain_completeness_rate"),
            "data_contamination_count": snapshot.get("data_contamination_count"),
        },
        "services": {
            "scheduler": snapshot.get("scheduler_running"),
            "worker": snapshot.get("worker_running"),
            "api": snapshot.get("api_responding"),
            "db": snapshot.get("db_responding"),
        },
        "disk_usage_pct": snapshot.get("disk_usage_pct"),
        "notes": snapshot.get("health_notes"),
    }


@router.get("/api/ops/metrics")
def get_operational_metrics(days: int = Query(30)):
    """Get historical operational health metrics."""
    with get_db() as conn:
        history = get_health_history(conn, days=min(days, 90))

    return {
        "days": days,
        "metrics": [
            {
                "date": h.get("snapshot_date"),
                "overall": h.get("overall_health_status"),
                "official_rate": h.get("official_collection_success_rate"),
                "odds_missing_rate": h.get("odds_snapshot_missing_rate"),
                "review_rate": h.get("review_generation_success_rate"),
                "backup_ok": h.get("backup_success"),
                "evidence_completeness": h.get("evidence_chain_completeness_rate"),
                "contamination": h.get("data_contamination_count"),
                "uptime_days": h.get("continuous_uptime_days"),
                "disk_pct": h.get("disk_usage_pct"),
            }
            for h in history
        ],
        "total": len(history),
    }


@router.get("/api/ops/evidence-chain")
def get_evidence_chain_audit(
    days: int = Query(7),
    show_broken: bool = Query(False),
):
    """Get evidence chain audit results."""
    with get_db() as conn:
        stats = get_evidence_chain_stats(conn, days=days)
        broken = get_broken_chains(conn, limit=50) if show_broken else []

    return {
        "period_days": days,
        "stats": stats,
        "broken_chains": broken if show_broken else [],
        "passes_stage8": stats["completeness_rate"] >= 1.0,
    }


@router.get("/api/ops/contamination-audit")
def get_contamination_audit(days: int = Query(30)):
    """Get data contamination audit results."""
    with get_db() as conn:
        stats = get_contamination_stats(conn, days=days)
        issues = get_recent_contamination_issues(conn, limit=50)

    return {
        "period_days": days,
        "stats": stats,
        "issues": issues,
        "passes_stage8": stats["contamination_found"] == 0,
    }


@router.get("/api/ops/backups")
def get_backup_status(days: int = Query(30)):
    """Get backup execution history and success rate."""
    with get_db() as conn:
        success_rate = get_backup_success_rate(conn, days=days)
        latest = get_latest_backup_log(conn)

    return {
        "period_days": days,
        "success_rate": success_rate,
        "latest_backup": latest,
        "passes_stage8": success_rate["success_rate"] >= 1.0,
    }
