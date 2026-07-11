"""Audit Sporttery-official historical match identity and local coverage.

This audit intentionally separates local identity integrity from completeness
against the official source. A clean local table does not prove that every
Sporttery-listed match was collected.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

from apps.backend.src.db import get_db
from scripts.official_history_importer import (
    normalize_official_match_code,
    official_match_identity_error,
)


def summarize_official_history_rows(
    rows: list[dict[str, Any]],
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    invalid_codes = 0
    weekday_mismatches = 0
    missing_team_names = 0
    missing_kickoff_time = 0

    for row in rows:
        business_date = str(row.get("business_date") or "")
        raw_code = str(row.get("official_match_code") or "")
        normalized_code = normalize_official_match_code(raw_code)
        error = official_match_identity_error(business_date, normalized_code)
        if error == "missing or invalid official display match code":
            invalid_codes += 1
        elif error in {"match code weekday does not match business_date", "invalid official business_date"}:
            weekday_mismatches += 1
        if not row.get("home_team_name") or not row.get("away_team_name"):
            missing_team_names += 1
        if not row.get("kickoff_time"):
            missing_kickoff_time += 1

    matches = len(rows)
    with_results = sum(bool(row.get("has_result")) for row in rows)
    with_source_id = sum(bool(row.get("source_match_id")) for row in rows)
    integrity_errors = (
        invalid_codes + weekday_mismatches + missing_team_names + missing_kickoff_time
    )
    return {
        "start_date": start_date,
        "end_date": end_date,
        "matches": matches,
        "business_days_with_matches": len(
            {str(row.get("business_date")) for row in rows if row.get("business_date")}
        ),
        "matches_with_results": with_results,
        "result_coverage_pct": round(with_results * 100 / matches, 2) if matches else 0.0,
        "matches_with_source_match_id": with_source_id,
        "source_match_id_coverage_pct": (
            round(with_source_id * 100 / matches, 2) if matches else 0.0
        ),
        "invalid_display_codes": invalid_codes,
        "weekday_mismatches": weekday_mismatches,
        "missing_team_names": missing_team_names,
        "missing_kickoff_time": missing_kickoff_time,
        "identity_integrity": "ok" if integrity_errors == 0 else "error",
        "source_completeness": "unverified_against_official_source",
    }


def audit_official_history(start_date: str, end_date: str) -> dict[str, Any]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT m.business_date::text, m.official_match_code,
                       m.source_match_id, (r.id IS NOT NULL) AS has_result,
                       m.home_team_name, m.away_team_name, m.kickoff_time
                FROM official_matches m
                LEFT JOIN official_results r ON r.match_id = m.id
                WHERE m.business_date BETWEEN %s AND %s
                ORDER BY m.business_date, m.official_match_code
                """,
                (start_date, end_date),
            )
            rows = [
                {
                    "business_date": row[0],
                    "official_match_code": row[1],
                    "source_match_id": row[2],
                    "has_result": row[3],
                    "home_team_name": row[4],
                    "away_team_name": row[5],
                    "kickoff_time": row[6].isoformat()
                    if hasattr(row[6], "isoformat")
                    else row[6],
                }
                for row in cur.fetchall()
            ]
    return summarize_official_history_rows(rows, start_date, end_date)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            audit_official_history(args.start_date, args.end_date),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
