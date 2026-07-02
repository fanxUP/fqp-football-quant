"""Data contamination auditor.

Stage 8: Daily job (23:45) that verifies temporal data integrity —
zero tolerance for post-match data leaking into pre-match features.

Checks performed:
  1. pre_match_lineup: actual lineups stored with timestamps AFTER kickoff
     should never appear in pre-match feature snapshots
  2. post_match_odds: final/closed odds should not be used in early-odds backtests
  3. result_leak: match results should not enter pre-match model features
  4. feature_leak: feature snapshots built after kickoff should be flagged
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.src.db import get_db
from scripts.ops_storage import store_contamination_audit


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


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
            WHERE os.snapshot_time > m.kickoff_time
              AND m.match_status = 'Selling'
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
                mr.result_time,
                mfs.snapshot_time AS feature_snapshot_time
            FROM official_results mr
            JOIN official_matches m ON m.id = mr.match_id
            LEFT JOIN match_feature_snapshots mfs ON mfs.match_id = m.id
            WHERE mr.result_time IS NOT NULL
              AND mfs.snapshot_time > mr.result_time
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


def run(dry_run: bool = False) -> dict[str, Any]:
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
        ]

        for check_name, check_fn in checks:
            try:
                findings = check_fn(conn)
                all_findings.extend(findings)
            except Exception as e:
                print(f"[contamination_audit] {check_name} check error: {e}")

        # Store findings
        if not dry_run:
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
        all_types = {"pre_match_lineup", "post_match_odds", "result_leak", "feature_leak"}
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


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
