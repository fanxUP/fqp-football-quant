"""Audit Sporttery-official historical match identity and local coverage.

This audit intentionally separates local identity integrity from completeness
against the official source. A clean local table does not prove that every
Sporttery-listed match was collected.
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.official_history_importer import (
    derive_business_date_from_match_date,
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
        elif error in {
            "match code weekday does not match business_date",
            "invalid official business_date",
        }:
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


def load_uniform_artifact_rows(artifact_dir: Path) -> tuple[int, list[dict[str, str]]]:
    """Read identities and season fields from retained Sporttery responses."""
    artifact_rows: list[dict[str, str]] = []
    pages = 0
    for artifact_path in sorted(artifact_dir.glob("*.json")):
        if artifact_path.name == "run_summary.json":
            continue
        document = json.loads(artifact_path.read_text(encoding="utf-8"))
        result_rows = ((document.get("response") or {}).get("value") or {}).get("matchResult")
        if not isinstance(result_rows, list):
            continue
        pages += 1
        for row in result_rows:
            if not isinstance(row, dict):
                continue
            match_id = row.get("matchId")
            if match_id is None:
                continue
            match_code = normalize_official_match_code(str(row.get("matchNumStr") or ""))
            artifact_rows.append(
                {
                    "match_id": str(match_id),
                    "league_name": str(row.get("leagueAllName") or row.get("leagueName") or ""),
                    "business_date": derive_business_date_from_match_date(
                        str(row.get("matchDate") or ""), match_code
                    ),
                }
            )
    return pages, artifact_rows


def load_uniform_artifact_match_ids(artifact_dir: Path) -> tuple[int, set[str]]:
    """Backward-compatible identity-only view of retained official artifacts."""
    pages, rows = load_uniform_artifact_rows(artifact_dir)
    return pages, {row["match_id"] for row in rows}


def select_in_scope_official_match_ids(
    *,
    artifact_rows: list[dict[str, str]],
    season_targets: dict[str, tuple[date | str, date | str]],
    start_date: str,
    end_date: str,
) -> tuple[set[str], int]:
    """Keep only artifact identities allowed by the selected-season database."""
    requested_start = date.fromisoformat(start_date)
    requested_end = date.fromisoformat(end_date)
    selected: set[str] = set()
    excluded_ids: set[str] = set()
    for row in artifact_rows:
        match_id = row.get("match_id", "")
        try:
            business_date = date.fromisoformat(row["business_date"])
        except KeyError, ValueError:
            if match_id:
                excluded_ids.add(match_id)
            continue
        raw_target = season_targets.get(row.get("league_name", ""))
        if season_targets and raw_target is None:
            if match_id:
                excluded_ids.add(match_id)
            continue
        if not season_targets:
            if requested_start <= business_date <= requested_end:
                selected.add(match_id)
            elif match_id:
                excluded_ids.add(match_id)
            continue
        assert raw_target is not None
        target_start = (
            raw_target[0] if isinstance(raw_target[0], date) else date.fromisoformat(raw_target[0])
        )
        target_end = (
            raw_target[1] if isinstance(raw_target[1], date) else date.fromisoformat(raw_target[1])
        )
        if (
            requested_start <= business_date <= requested_end
            and target_start <= business_date <= target_end
        ):
            selected.add(match_id)
        else:
            if match_id:
                excluded_ids.add(match_id)
    return selected, len(excluded_ids - selected)


def summarize_official_artifact_coverage(
    *,
    official_match_ids: set[str],
    database_match_ids: set[str],
    artifact_pages: int,
    excluded_match_ids: int | None = None,
) -> dict[str, Any]:
    """Summarize whether retained official response identities reached the DB."""
    missing = official_match_ids - database_match_ids
    if not official_match_ids:
        status = "unverified_against_official_source"
    elif missing:
        status = "incomplete_against_official_artifacts"
    else:
        status = "verified_against_official_artifacts"
    result = {
        "official_artifact_pages": artifact_pages,
        "official_distinct_match_ids": len(official_match_ids),
        "database_match_ids_present": len(database_match_ids),
        "missing_database_match_ids": len(missing),
        "source_completeness": status,
    }
    if excluded_match_ids is not None:
        result["artifact_match_ids_outside_selected_seasons"] = excluded_match_ids
    return result


def audit_official_history(
    start_date: str,
    end_date: str,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_pages, artifact_rows = (
        load_uniform_artifact_rows(artifact_dir) if artifact_dir else (0, [])
    )
    artifact_match_ids: set[str] = set()
    excluded_match_ids = 0
    with get_db() as conn:
        with conn.cursor() as cur:
            if artifact_rows:
                cur.execute(
                    "SELECT league_name, season_start_date, season_end_date "
                    "FROM official_event_season_targets"
                )
                season_targets = {row[0]: (row[1], row[2]) for row in cur.fetchall()}
                artifact_match_ids, excluded_match_ids = select_in_scope_official_match_ids(
                    artifact_rows=artifact_rows,
                    season_targets=season_targets,
                    start_date=start_date,
                    end_date=end_date,
                )
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
                    "kickoff_time": row[6].isoformat() if hasattr(row[6], "isoformat") else row[6],
                }
                for row in cur.fetchall()
            ]
            database_match_ids: set[str] = set()
            if artifact_match_ids:
                cur.execute(
                    "SELECT source_match_id FROM official_matches WHERE source_match_id = ANY(%s)",
                    (list(artifact_match_ids),),
                )
                database_match_ids = {str(row[0]) for row in cur.fetchall()}

    summary = summarize_official_history_rows(rows, start_date, end_date)
    if artifact_dir:
        summary.update(
            summarize_official_artifact_coverage(
                official_match_ids=artifact_match_ids,
                database_match_ids=database_match_ids,
                artifact_pages=artifact_pages,
                excluded_match_ids=excluded_match_ids,
            )
        )
        summary["official_artifact_dir"] = str(artifact_dir)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        help="Directory created by backfill_uniform_official_history for source coverage verification",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            audit_official_history(args.start_date, args.end_date, args.artifact_dir),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
