"""Remove rows whose match identity cannot be verified as Sporttery official."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db

OFFICIAL_CODE_RE = re.compile(r"^周[一二三四五六日][0-9]{3}$")
NONOFFICIAL_SOURCES = {"500.com", "third_party", "supplemental"}

BAD_MATCH_SQL = """
SELECT id
FROM official_matches
WHERE NOT (
    official_match_code ~ '^周[一二三四五六日][0-9]{3}$'
    AND NULLIF(BTRIM(source_match_id), '') IS NOT NULL
    AND LOWER(COALESCE(raw_json->>'source', ''))
        NOT IN ('500.com', 'third_party', 'supplemental')
)
"""


def _delete_by_match_id(table: str) -> str:
    return f"DELETE FROM {table} WHERE match_id IN (SELECT id FROM cleanup_bad_match_ids)"


# The order is a dependency contract. In particular, tickets and error rows
# reference predictions, predictions reference odds/features, and odds
# reference markets.
DELETE_STEPS: list[tuple[str, str]] = [
    ("simulation_ticket_items", _delete_by_match_id("simulation_ticket_items")),
    ("prediction_error_analysis", _delete_by_match_id("prediction_error_analysis")),
    ("model_predictions", _delete_by_match_id("model_predictions")),
    ("simulator_ticket_items", _delete_by_match_id("simulator_ticket_items")),
    ("real_ticket_items", _delete_by_match_id("real_ticket_items")),
    ("football_pool_issue_matches", _delete_by_match_id("football_pool_issue_matches")),
    ("score_distribution_snapshots", _delete_by_match_id("score_distribution_snapshots")),
    ("model_committee_votes", _delete_by_match_id("model_committee_votes")),
    ("market_efficiency_metrics", _delete_by_match_id("market_efficiency_metrics")),
    ("odds_probability_conversions", _delete_by_match_id("odds_probability_conversions")),
    ("official_results", _delete_by_match_id("official_results")),
    ("official_odds_snapshots", _delete_by_match_id("official_odds_snapshots")),
    ("official_markets", _delete_by_match_id("official_markets")),
    ("match_feature_snapshots", _delete_by_match_id("match_feature_snapshots")),
    ("match_lineup_snapshots", _delete_by_match_id("match_lineup_snapshots")),
    ("match_travel_features", _delete_by_match_id("match_travel_features")),
    ("match_weather_snapshots", _delete_by_match_id("match_weather_snapshots")),
    ("team_motivation_snapshots", _delete_by_match_id("team_motivation_snapshots")),
    (
        "tournament_incentive_snapshots",
        _delete_by_match_id("tournament_incentive_snapshots"),
    ),
    (
        "recommendation_shutdown_events",
        _delete_by_match_id("recommendation_shutdown_events"),
    ),
    (
        "data_contamination_audit_logs",
        _delete_by_match_id("data_contamination_audit_logs"),
    ),
    ("elo_update_logs", _delete_by_match_id("elo_update_logs")),
    (
        "official_matches",
        "DELETE FROM official_matches WHERE id IN (SELECT id FROM cleanup_bad_match_ids)",
    ),
    ("supplemental_matches", "DELETE FROM supplemental_matches"),
]


def official_identity_is_valid(
    official_match_code: str | None,
    source_match_id: str | None,
    raw_source: str | None,
) -> bool:
    return bool(
        official_match_code
        and OFFICIAL_CODE_RE.fullmatch(official_match_code)
        and source_match_id
        and str(source_match_id).strip()
        and (raw_source or "").lower() not in NONOFFICIAL_SOURCES
    )


def _count_targets(conn: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    with conn.cursor() as cur:
        for name, _sql in DELETE_STEPS:
            if name == "official_matches":
                cur.execute("SELECT COUNT(*) FROM cleanup_bad_match_ids")
            elif name == "supplemental_matches":
                cur.execute("SELECT COUNT(*) FROM supplemental_matches")
            else:
                cur.execute(
                    f"SELECT COUNT(*) FROM {name} "
                    "WHERE match_id IN (SELECT id FROM cleanup_bad_match_ids)"
                )
            counts[name] = int(cur.fetchone()[0])
    return counts


def _ensure_identity_constraint(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM pg_constraint
            WHERE conrelid = 'official_matches'::regclass
              AND conname = 'official_matches_display_code_format'
            """
        )
        if cur.fetchone() is None:
            cur.execute(
                """
                ALTER TABLE official_matches
                ADD CONSTRAINT official_matches_display_code_format
                CHECK (official_match_code ~ '^周[一二三四五六日][0-9]{3}$') NOT VALID
                """
            )
        cur.execute(
            "ALTER TABLE official_matches VALIDATE CONSTRAINT official_matches_display_code_format"
        )


def run(
    *,
    execute: bool = False,
    backup_path: Path | None = None,
    report_root: Path = Path("data/cleanup"),
) -> dict[str, Any]:
    """Preview or execute strict official-match cleanup in one transaction."""
    if execute and (backup_path is None or not backup_path.is_file()):
        raise ValueError("--execute requires an existing --backup file")
    timestamp = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y%m%d-%H%M%S")
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE cleanup_bad_match_ids (id BIGINT PRIMARY KEY) ON COMMIT DROP"
            )
            cur.execute("INSERT INTO cleanup_bad_match_ids " + BAD_MATCH_SQL)
            cur.execute("SELECT COUNT(*) FROM official_matches")
            total_matches = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM cleanup_bad_match_ids")
            bad_matches = int(cur.fetchone()[0])
        preserved_matches = total_matches - bad_matches
        if execute and total_matches > 0 and preserved_matches == 0:
            conn.rollback()
            raise RuntimeError("cleanup would remove every official match; refusing to execute")

        target_counts = _count_targets(conn)
        deleted: dict[str, int] = {name: 0 for name, _sql in DELETE_STEPS}
        if execute:
            with conn.cursor() as cur:
                for name, sql in DELETE_STEPS:
                    cur.execute(sql)
                    deleted[name] = cur.rowcount
            _ensure_identity_constraint(conn)
            conn.commit()
        else:
            conn.rollback()

    report = {
        "status": "executed" if execute else "dry_run",
        "generated_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds"),
        "backup_path": str(backup_path.resolve()) if backup_path else None,
        "official_matches_before": total_matches,
        "official_matches_preserved": preserved_matches,
        "target_counts": target_counts,
        "deleted": deleted,
        "official_identity_rule": {
            "display_code": "^周[一二三四五六日][0-9]{3}$",
            "source_match_id_required": True,
            "blocked_raw_sources": sorted(NONOFFICIAL_SOURCES),
        },
    }
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / f"official_match_cleanup_{timestamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path.resolve())
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(run(execute=args.execute, backup_path=args.backup), ensure_ascii=False, indent=2)
    )
