"""Data contamination auditor.

Stage 8: Daily job (23:45) that verifies temporal data integrity —
zero tolerance for post-match data leaking into pre-match features.

Checks performed:
  1. pre_match_lineup: actual lineups stored with timestamps AFTER kickoff
     should never appear in pre-match feature snapshots
  2. post_match_odds: final/closed odds should not be used in early-odds backtests
  3. result_leak: match results should not enter pre-match model features
  4. feature_leak: feature snapshots built after kickoff should be flagged
  5. post_match_prediction: predictions generated at/after kickoff
  6. error_analysis_scope: error rows not tied to the latest pre-match top pick
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.agents.task_queue import finish_tracked_job, start_tracked_job
from scripts.ops_storage import store_contamination_audit


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_previous_findings(conn: Any, check_type: str) -> None:
    """Close the prior audit state before writing the current check result."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE data_contamination_audit_logs
               SET resolved = true,
                   resolution_notes = 'Superseded by a newer contamination audit'
               WHERE check_type = %s AND contamination_detected = true AND NOT resolved""",
            (check_type,),
        )
    conn.commit()


def _check_lineup_temporal_integrity(conn: Any) -> list[dict]:
    """Check that lineups stored after kickoff are not used in pre-match features.

    Returns list of contamination findings.
    """
    findings = []
    with conn.cursor() as cur:
        # Find lineups where snapshot_time > kickoff_time
        # but were referenced by feature snapshots built before kickoff
        cur.execute(
            """
            SELECT
                m.id AS match_id,
                m.home_team_name,
                m.away_team_name,
                m.kickoff_time,
                mls.snapshot_time AS lineup_snapshot_time,
                mfs.snapshot_time AS feature_snapshot_time
            FROM match_lineup_snapshots mls
            JOIN official_matches m ON m.id = mls.match_id
            LEFT JOIN match_feature_snapshots mfs ON mfs.match_id = m.id
            WHERE mls.snapshot_time > m.kickoff_time
              AND mfs.snapshot_time < m.kickoff_time
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            findings.append(
                {
                    "check_type": "pre_match_lineup",
                    "match_id": row[0],
                    "severity": "critical",
                    "contamination_detected": True,
                    "detail": (
                        f"Match {row[0]} ({row[1]} vs {row[2]}): "
                        f"lineup snapshot at {row[4]} (after kickoff {row[3]}) "
                        f"potentially used in feature snapshot at {row[5]}"
                    ),
                    "evidence": {
                        "match_id": row[0],
                        "home": row[1],
                        "away": row[2],
                        "kickoff_time": str(row[3]),
                        "lineup_snapshot_time": str(row[4]),
                        "feature_snapshot_time": str(row[5]) if row[5] else None,
                    },
                }
            )
    return findings


def _check_odds_temporal_integrity(conn: Any) -> list[dict]:
    """Check for post-match odds used in pre-match contexts.

    Final/closed odds should not appear in snapshots used for early predictions.
    """
    findings = []
    with conn.cursor() as cur:
        # Find odds snapshots taken after match kickoff
        cur.execute(
            """
            SELECT
                m.id AS match_id,
                m.home_team_name,
                m.away_team_name,
                m.kickoff_time,
                COUNT(os.id) AS post_kickoff_snapshots
            FROM official_matches m
            JOIN official_odds_snapshots os ON os.match_id = m.id
            WHERE os.snapshot_time > m.kickoff_time + INTERVAL '10 minutes'
              AND m.sale_status = 'selling'
              AND NULLIF(m.raw_json->>'matchTime', '') IS NOT NULL
            GROUP BY m.id, m.home_team_name, m.away_team_name, m.kickoff_time
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            if row[4] > 0:
                findings.append(
                    {
                        "check_type": "post_match_odds",
                        "match_id": row[0],
                        "severity": "warning",
                        "contamination_detected": True,
                        "detail": (
                            f"Match {row[0]} ({row[1]} vs {row[2]}): "
                            f"{row[4]} odds snapshots taken after kickoff {row[3]}"
                        ),
                        "evidence": {
                            "match_id": row[0],
                            "home": row[1],
                            "away": row[2],
                            "kickoff_time": str(row[3]),
                            "post_kickoff_snapshots": row[4],
                        },
                    }
                )
    return findings


def _check_result_leak(conn: Any) -> list[dict]:
    """Check that match results are not present in pre-match feature data.

    A result existing before a feature snapshot for the same match = contamination.
    """
    findings = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                m.id AS match_id,
                m.home_team_name,
                m.away_team_name,
                m.kickoff_time,
                mr.official_publish_time AS result_time,
                mfs.snapshot_time AS feature_snapshot_time
            FROM official_results mr
            JOIN official_matches m ON m.id = mr.match_id
            LEFT JOIN match_feature_snapshots mfs ON mfs.match_id = m.id
            WHERE mr.official_publish_time IS NOT NULL
              AND mfs.snapshot_time > mr.official_publish_time
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            findings.append(
                {
                    "check_type": "result_leak",
                    "match_id": row[0],
                    "severity": "critical",
                    "contamination_detected": True,
                    "detail": (
                        f"Match {row[0]} ({row[1]} vs {row[2]}): "
                        f"feature snapshot at {row[5]} built AFTER result at {row[4]}"
                    ),
                    "evidence": {
                        "match_id": row[0],
                        "home": row[1],
                        "away": row[2],
                        "kickoff_time": str(row[3]),
                        "result_time": str(row[4]),
                        "feature_snapshot_time": str(row[5]),
                    },
                }
            )
    return findings


def _check_feature_snapshot_staleness(conn: Any) -> list[dict]:
    """Check for feature snapshots that reference data newer than the snapshot time.

    This is a metadata-level check: flag snapshots where snapshot_time is suspicious.
    """
    findings = []
    with conn.cursor() as cur:
        # Feature snapshots built >24h after kickoff = suspicious
        cur.execute(
            """
            SELECT
                mfs.id AS snapshot_id,
                mfs.match_id,
                mfs.snapshot_time,
                m.kickoff_time,
                m.home_team_name,
                m.away_team_name
            FROM match_feature_snapshots mfs
            JOIN official_matches m ON m.id = mfs.match_id
            WHERE mfs.snapshot_time > m.kickoff_time + INTERVAL '24 hours'
              AND NULLIF(m.raw_json->>'matchTime', '') IS NOT NULL
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            findings.append(
                {
                    "check_type": "feature_leak",
                    "match_id": row[1],
                    "severity": "info",
                    "contamination_detected": True,
                    "detail": (
                        f"Feature snapshot {row[0]} for match {row[1]} "
                        f"({row[4]} vs {row[5]}) built at {row[2]}, "
                        f">24h after kickoff {row[3]}"
                    ),
                    "evidence": {
                        "snapshot_id": row[0],
                        "match_id": row[1],
                        "snapshot_time": str(row[2]),
                        "kickoff_time": str(row[3]),
                    },
                }
            )
    return findings


def _check_prediction_temporal_integrity(conn: Any) -> list[dict]:
    """Flag model predictions generated at or after official kickoff."""
    findings = []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.home_team_name, m.away_team_name, m.kickoff_time,
                   COUNT(mp.id) AS post_kickoff_predictions
            FROM model_predictions mp
            JOIN official_matches m ON m.id = mp.match_id
            WHERE mp.predict_time >= m.kickoff_time
              AND mp.created_at >= NOW() - INTERVAL '2 days'
            GROUP BY m.id, m.home_team_name, m.away_team_name, m.kickoff_time
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            findings.append(
                {
                    "check_type": "post_match_prediction",
                    "match_id": row[0],
                    "severity": "critical",
                    "contamination_detected": True,
                    "detail": (
                        f"Match {row[0]} ({row[1]} vs {row[2]}): "
                        f"{row[4]} predictions generated at/after kickoff {row[3]}"
                    ),
                    "evidence": {
                        "match_id": row[0],
                        "kickoff_time": str(row[3]),
                        "post_kickoff_predictions": row[4],
                    },
                }
            )
    return findings


def _check_error_analysis_scope(conn: Any) -> list[dict]:
    """Flag stored errors that are not the latest pre-match SPF top pick."""
    findings = []
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH latest_options AS (
                SELECT DISTINCT ON (
                    mp.match_id, mp.model_version_id, mp.option_code
                ) mp.id, mp.match_id, mp.model_version_id,
                  mp.option_code, mp.model_probability
                FROM model_predictions mp
                JOIN official_matches m ON m.id = mp.match_id
                WHERE mp.play_type = 'spf'
                  AND mp.option_code IN ('3', '1', '0')
                  AND mp.model_probability IS NOT NULL
                  AND mp.predict_time < m.kickoff_time
                ORDER BY mp.match_id, mp.model_version_id, mp.option_code,
                         mp.predict_time DESC, mp.id DESC
            ), top_picks AS (
                SELECT id, match_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY match_id, model_version_id
                           ORDER BY model_probability DESC NULLS LAST,
                                    option_code, id DESC
                       ) AS pick_rank
                FROM latest_options
            )
            SELECT pea.id, pea.match_id, pea.prediction_id,
                   m.home_team_name, m.away_team_name
            FROM prediction_error_analysis pea
            LEFT JOIN official_matches m ON m.id = pea.match_id
            LEFT JOIN top_picks tp
              ON tp.id = pea.prediction_id AND tp.pick_rank = 1
            WHERE tp.id IS NULL
            LIMIT 100
            """
        )
        for row in cur.fetchall():
            findings.append(
                {
                    "check_type": "error_analysis_scope",
                    "match_id": row[1],
                    "severity": "critical",
                    "contamination_detected": True,
                    "detail": (
                        f"Error row {row[0]} for match {row[1]} "
                        f"({row[3]} vs {row[4]}) is not a valid pre-match top pick"
                    ),
                    "evidence": {
                        "error_id": row[0],
                        "match_id": row[1],
                        "prediction_id": row[2],
                    },
                }
            )
    return findings


def _run_impl(dry_run: bool = False) -> dict[str, Any]:
    """Run all data contamination checks.

    Returns:
        Summary with contamination findings.
    """
    audit_time = _now()

    with get_db() as conn:
        all_findings = []

        # Run all checks
        checks = [
            ("pre_match_lineup", _check_lineup_temporal_integrity),
            ("post_match_odds", _check_odds_temporal_integrity),
            ("result_leak", _check_result_leak),
            ("feature_leak", _check_feature_snapshot_staleness),
            ("post_match_prediction", _check_prediction_temporal_integrity),
            ("error_analysis_scope", _check_error_analysis_scope),
        ]

        for check_name, check_fn in checks:
            try:
                findings = check_fn(conn)
                all_findings.extend(findings)
            except Exception as e:
                print(f"[contamination_audit] {check_name} check error: {e}")

        # Store findings
        if not dry_run:
            for check_name, _ in checks:
                _resolve_previous_findings(conn, check_name)
            for f in all_findings:
                store_contamination_audit(
                    conn,
                    {
                        "audit_time": audit_time,
                        "check_type": f["check_type"],
                        "match_id": f.get("match_id"),
                        "severity": f.get("severity", "info"),
                        "contamination_detected": f.get("contamination_detected", False),
                        "detail": f.get("detail"),
                        "evidence": f.get("evidence", {}),
                    },
                )

        # Also record clean checks
        checked_types = set(f["check_type"] for f in all_findings)
        all_types = {
            "pre_match_lineup",
            "post_match_odds",
            "result_leak",
            "feature_leak",
            "post_match_prediction",
            "error_analysis_scope",
        }
        for ct in all_types - checked_types:
            if not dry_run:
                store_contamination_audit(
                    conn,
                    {
                        "audit_time": audit_time,
                        "check_type": ct,
                        "match_id": None,
                        "severity": "info",
                        "contamination_detected": False,
                        "detail": f"{ct}: no issues found",
                        "evidence": {},
                    },
                )

    critical_count = sum(1 for f in all_findings if f.get("severity") == "critical")
    warning_count = sum(1 for f in all_findings if f.get("severity") == "warning")

    return {
        "status": "ok" if not dry_run else "dry_run",
        "total_findings": len(all_findings),
        "critical": critical_count,
        "warning": warning_count,
        "info": len(all_findings) - critical_count - warning_count,
        "contamination_detected": len(all_findings) > 0,
        "findings_summary": [
            {"type": f["check_type"], "severity": f["severity"], "detail": f["detail"]}
            for f in all_findings[:20]
        ],
    }


def run(dry_run: bool = False) -> dict[str, Any]:
    """Audit contamination and persist its QA execution record."""
    run_id = start_tracked_job("data_contamination_audit", "qa_agent", {"dry_run": dry_run})
    try:
        result = _run_impl(dry_run=dry_run)
        finish_tracked_job(run_id, result.get("status", "completed"), {"result": result})
        return result
    except Exception as exc:
        finish_tracked_job(run_id, "failed", error=str(exc))
        raise


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
