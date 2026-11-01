"""Plan or apply bounded imports from the Sporttery official history API.

The default path is file-only. PostgreSQL writes require ``--apply``, an
explicit local/loopback ``DATABASE_URL``, and the exact applied migration 128
checksum. ``--kind new`` inserts missing issue keys; ``--kind fill`` only adds
source facts to exact existing rosters after live slot identity checks. Neither
path replaces saved identities, fixture links, or model values.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import parse_dsn
from psycopg2.extras import Json

CONTRACT = "sporttery-traditional-history-import/v1"
EXPECTED = {"t14c": (90, 14), "r9": (90, 14), "bqc6": (98, 6), "jq4": (94, 4)}
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MIGRATION = ROOT / "sql" / "128_traditional_history_facts.sql"
DEFAULT_PLAN_DIR = (
    ROOT.parent
    / "plans"
    / "local-football-data-integration-20261029"
    / "traditional-catalog-20261101"
)


def default_input_paths() -> tuple[Path, Path, Path]:
    """Paths to the latest API-complete planning snapshot in this checkout."""
    stem = "TRADITIONAL-HISTORY-IMPORT"
    version = "API-COMPLETE-20261101"
    return (
        DEFAULT_PLAN_DIR / f"{stem}-PREVIEW-{version}.csv",
        DEFAULT_PLAN_DIR / f"{stem}-MANIFEST-{version}.csv",
        DEFAULT_PLAN_DIR / f"{stem}-MANIFEST-{version}.json",
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _json_object(row: dict[str, str], key: str) -> dict[str, Any]:
    value = row.get(key, "")
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{key} must contain a JSON object")
    return parsed


def _optional_nonnegative_int(value: str, field: str) -> int | None:
    if value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a nonnegative integer or empty") from exc
    if parsed < 0:
        raise ValueError(f"{field} must be nonnegative")
    return parsed


def _notice_evidence(row: dict[str, str]) -> dict[str, Any]:
    return {
        "competition": row.get("notice_competition") or None,
        "home": row.get("notice_home") or None,
        "away": row.get("notice_away") or None,
        "match_date": row.get("notice_match_date") or None,
        "notice_id": row.get("notice_id") or None,
        "notice_url": row.get("notice_url") or None,
        "has_later_incomplete_notice": row.get("notice_has_later_incomplete") == "true",
        "api_reconciliation": row.get("notice_api_reconciliation") or None,
    }


def _build_issue(
    rows: list[dict[str, str]],
    *,
    preview_sha256: str,
    manifest_sha256: str,
    manifest_row: dict[str, str],
    operation: str = "new",
) -> dict[str, Any]:
    first = rows[0]
    game_type = first["game_type"]
    issue_no = first["issue_no"]
    expected_source_game_no, expected_slots = EXPECTED.get(game_type, (None, None))
    if expected_source_game_no is None:
        raise ValueError(f"unsupported traditional game type: {game_type}")
    if int(first["source_game_no"]) != expected_source_game_no:
        raise ValueError(f"{game_type}/{issue_no} source gameNo mismatch")
    if int(manifest_row["source_game_no"]) != expected_source_game_no:
        raise ValueError(f"{game_type}/{issue_no} manifest gameNo mismatch")
    if first["source_game_no_source"] != "sporttery_history_api":
        raise ValueError(f"{game_type}/{issue_no} has an unexpected source namespace")
    if manifest_row["source_game_no_source"] != "sporttery_history_api":
        raise ValueError(f"{game_type}/{issue_no} manifest namespace mismatch")
    expected_state = {
        "new": "missing_issue_key",
        "fill": "existing_issue_matches_source_api",
    }.get(operation)
    expected_readiness = {
        "new": "candidate_new_issue",
        "fill": "candidate_fill_exact_existing_issue",
    }.get(operation)
    if expected_state is None:
        raise ValueError(f"unsupported import operation: {operation}")
    if manifest_row["production_issue_state"] != expected_state:
        raise ValueError(f"{game_type}/{issue_no} is not an eligible {operation} candidate")
    if manifest_row.get("readiness") != expected_readiness:
        raise ValueError(f"{game_type}/{issue_no} manifest readiness disagrees with {operation}")
    if manifest_row.get("blocking_reasons", ""):
        raise ValueError(f"{game_type}/{issue_no} contains manifest blockers")
    if operation == "fill" and any(
        row.get("production_member_slot_exact_team_date") != "true" for row in rows
    ):
        raise ValueError(f"{game_type}/{issue_no} has a non-exact existing production slot")

    ordered = sorted(rows, key=lambda row: int(row["match_order"]))
    orders = [int(row["match_order"]) for row in ordered]
    if len(ordered) != expected_slots or orders != list(range(1, expected_slots + 1)):
        raise ValueError(f"{game_type}/{issue_no} has an incomplete or duplicate API slot order")
    if (
        int(manifest_row["preview_rows"]) != len(ordered)
        or int(manifest_row["expected_slots"]) != expected_slots
    ):
        raise ValueError(f"{game_type}/{issue_no} preview disagrees with its import manifest")

    sale_start = first.get("history_sale_start") or None
    sale_stop = first.get("history_sale_stop") or None
    if bool(sale_start) != bool(sale_stop):
        raise ValueError(f"{game_type}/{issue_no} has only one API sale-window boundary")
    for value in (sale_start, sale_stop):
        if value:
            try:
                datetime.fromisoformat(value)
            except ValueError as exc:
                raise ValueError(f"{game_type}/{issue_no} has an invalid API sale window") from exc
    issue_evidence = {
        "source": "sporttery_history_api",
        "source_game_no": expected_source_game_no,
        "history_game_name": first.get("history_game_name") or None,
        "history_draw_time": first.get("history_draw_time") or None,
        "sale_begin": sale_start,
        "sale_end": sale_stop,
        "notice_ids": sorted({row["notice_id"] for row in ordered if row.get("notice_id")}),
        "notice_policy": "secondary_evidence; never merged into or reordered over official API slots",
        "preview_sha256": preview_sha256,
        "manifest_sha256": manifest_sha256,
    }
    matches: list[dict[str, Any]] = []
    source_row_hashes: list[str] = []
    for row in ordered:
        if any(
            row.get(key) != first.get(key)
            for key in (
                "game_type",
                "issue_no",
                "source_game_no",
                "source_game_no_source",
                "history_sale_start",
                "history_sale_stop",
            )
        ):
            raise ValueError(f"{game_type}/{issue_no} contains inconsistent issue-level fields")
        if (
            not row.get("history_home")
            or not row.get("history_away")
            or not row.get("kickoff_date")
        ):
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} lacks team/date facts"
            )
        try:
            date.fromisoformat(row["kickoff_date"])
        except ValueError as exc:
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} has an invalid date"
            ) from exc
        if not row.get("source_product_result_code"):
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} lacks product result code"
            )
        if row.get("source_result_source") != "sporttery_history_api":
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} result source mismatch"
            )
        if row.get("source_result_semantics_key") != f"sporttery_game_no_{expected_source_game_no}":
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} result semantics mismatch"
            )

        score_text = row.get("full_score_source_text", "").strip()
        result_code = row["source_product_result_code"].strip()
        source_marks_unplayed = score_text == "*" and "*" in result_code.split(",")
        score_state = row.get("score_source_state")
        if score_state == "present":
            full_home = _optional_nonnegative_int(
                row.get("source_full_home_goals", ""), "home goals"
            )
            full_away = _optional_nonnegative_int(
                row.get("source_full_away_goals", ""), "away goals"
            )
            if full_home is None or full_away is None:
                raise ValueError(
                    f"{game_type}/{issue_no} slot {row['match_order']} has an unparsed score"
                )
        elif source_marks_unplayed and score_state == "source_marks_unplayed_or_unparsed":
            full_home = full_away = None
        else:
            raise ValueError(
                f"{game_type}/{issue_no} slot {row['match_order']} has an ambiguous score state"
            )

        home = _optional_nonnegative_int(
            row.get("source_half_home_goals", ""), "half-time home goals"
        )
        away = _optional_nonnegative_int(
            row.get("source_half_away_goals", ""), "half-time away goals"
        )
        kickoff_evidence = _json_object(row, "kickoff_evidence_json")
        result_evidence = _json_object(row, "source_result_evidence_json")
        notice = _notice_evidence(row)
        result_evidence["notice_evidence"] = notice
        result_evidence["notice_api_reconciliation"] = notice["api_reconciliation"]
        result_evidence["score_source_state"] = score_state
        source_match_id = row.get("sporttery_match_id") or None
        raw_source = {
            "source": "sporttery_history_api",
            "source_game_no": expected_source_game_no,
            "issue_no": issue_no,
            "match_num": int(row["match_order"]),
            "league_name": row.get("history_competition") or None,
            "home_team_name": row["history_home"],
            "away_team_name": row["history_away"],
            "kickoff_date": row["kickoff_date"],
            "kickoff_time_precision": "date_only",
            "full_score_source_text": row.get("full_score_source_text") or None,
            "half_score_source_text": row.get("half_score_source_text") or None,
            "product_result_code_source_text": result_code,
            "sporttery_match_id": source_match_id,
            "titan_match_id_direct": row.get("titan_match_id_direct") or None,
            "titan_match_id_candidate": row.get("titan_match_id_candidate") or None,
            "notice_evidence": notice,
            "history_mirror_updated_at": row.get("history_mirror_updated_at") or None,
        }
        kickoff_evidence["source"] = "sporttery_history_api"
        kickoff_evidence["precision"] = "date_only"
        identity_evidence = {
            "status": "pending",
            "reason": "source identity is retained, but no shared fixture assignment was approved",
            "source": "sporttery_history_api",
            "source_match_id": source_match_id,
        }
        member: dict[str, Any] = {
            "match_order": int(row["match_order"]),
            "match_id": None,
            "source_match_id": source_match_id,
            "league_name": row.get("history_competition") or None,
            "home_team_name": row["history_home"],
            "away_team_name": row["history_away"],
            "kickoff_time": None,
            "kickoff_date": row["kickoff_date"],
            "kickoff_time_precision": "date_only",
            "kickoff_evidence": kickoff_evidence,
            "source_full_home_goals": full_home,
            "source_full_away_goals": full_away,
            "source_half_home_goals": home,
            "source_half_away_goals": away,
            "source_product_result_code": result_code,
            "source_result_semantics_key": f"sporttery_game_no_{expected_source_game_no}",
            "source_result_source": "sporttery_history_api",
            "source_result_evidence": result_evidence,
            "home_win_prob": None,
            "draw_prob": None,
            "away_win_prob": None,
            "upset_score": None,
            "public_heat_home": None,
            "public_heat_draw": None,
            "public_heat_away": None,
            "fixture_id": None,
            "identity_status": "pending",
            "identity_evidence": identity_evidence,
            "source_raw_json": raw_source,
        }
        source_row_hashes.append(_sha256(row))
        matches.append(member)

    issue_sha256 = _sha256({"issue": issue_evidence, "matches": matches})
    for member, source_row_hash in zip(matches, source_row_hashes, strict=True):
        member["source_raw_json"]["import_receipt"] = {
            "contract": CONTRACT,
            "issue_sha256": issue_sha256,
            "manifest_sha256": manifest_sha256,
            "source_row_sha256": source_row_hash,
        }
    raw_json = {
        **issue_evidence,
        "import_receipt": {
            "contract": CONTRACT,
            "issue_sha256": issue_sha256,
            "manifest_sha256": manifest_sha256,
        },
    }
    return {
        "game_type": game_type,
        "issue_no": issue_no,
        "source_game_type": game_type,
        "source_game_no": expected_source_game_no,
        "source_game_no_source": "sporttery_history_api",
        "sale_start_time": sale_start,
        "sale_stop_time": sale_stop,
        "total_matches": expected_slots,
        "official_status": "closed",
        "raw_json": raw_json,
        "raw_hash": _pool_raw_hash(raw_json),
        "issue_sha256": issue_sha256,
        "issue_operation": operation,
        "matches": matches,
    }


def load_issue_batch(
    preview_path: Path,
    manifest_path: Path,
    summary_path: Path,
    *,
    offset: int = 0,
    limit: int = 25,
    kind: str = "new",
) -> dict[str, Any]:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 100")
    preview_sha256 = hashlib.sha256(preview_path.read_bytes()).hexdigest()
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("input_sha256") != preview_sha256:
        raise ValueError("preview SHA-256 does not match the import manifest")
    if summary.get("manifest_sha256") != manifest_sha256:
        raise ValueError("manifest SHA-256 does not match the import summary")
    manifest_rows = _read_csv(manifest_path)
    manifest_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in manifest_rows:
        key = (row["game_type"], row["issue_no"])
        if key in manifest_by_key:
            raise ValueError(f"duplicate issue in manifest: {key[0]}/{key[1]}")
        manifest_by_key[key] = row

    grouped: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(preview_path):
        grouped[(row["game_type"], row["issue_no"])].append(row)
    if set(grouped) != set(manifest_by_key):
        raise ValueError("manifest issue keys do not match the slot preview")

    readiness = {
        "new": "candidate_new_issue",
        "fill": "candidate_fill_exact_existing_issue",
    }.get(kind)
    if readiness is None:
        raise ValueError(f"unsupported import kind: {kind}")
    candidates = [
        (key, row)
        for key, row in sorted(manifest_by_key.items())
        if row.get("readiness") == readiness
    ]
    if offset > len(candidates):
        raise ValueError("offset is beyond the candidate issue list")
    stop = offset + limit
    issues = []
    for index, (key, manifest_row) in enumerate(candidates):
        issue = _build_issue(
            grouped[key],
            preview_sha256=preview_sha256,
            manifest_sha256=manifest_sha256,
            manifest_row=manifest_row,
            operation=kind,
        )
        if offset <= index < stop:
            issues.append(issue)
    return {
        "contract": CONTRACT,
        "issue_operation": kind,
        "preview_sha256": preview_sha256,
        "manifest_sha256": manifest_sha256,
        "candidate_issue_count": len(candidates),
        "validated_candidate_issue_count": len(candidates),
        "offset": offset,
        "selected_issue_count": len(issues),
        "selected_member_count": sum(len(issue["matches"]) for issue in issues),
        "first_issue": f"{issues[0]['game_type']}/{issues[0]['issue_no']}" if issues else None,
        "last_issue": f"{issues[-1]['game_type']}/{issues[-1]['issue_no']}" if issues else None,
        "issues": issues,
    }


def _local_database_parameters() -> dict[str, str]:
    if {"PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS"}.intersection(os.environ):
        raise ValueError("PostgreSQL service/hostaddr overrides are not allowed for this import")
    dsn = os.environ.get("DATABASE_URL", "").strip()
    try:
        params = parse_dsn(dsn) if dsn else {}
    except psycopg2.Error as exc:
        raise ValueError("DATABASE_URL is not a valid explicit local DSN") from exc
    host = params.get("host", "")
    if host not in LOOPBACK and host != "/var/run/postgresql":
        raise ValueError("--apply requires a loopback or local PostgreSQL socket DATABASE_URL")
    if "service" in params or "servicefile" in params:
        raise ValueError("PostgreSQL service DSNs are not allowed for this import")
    if params.get("hostaddr") and params["hostaddr"] not in {"127.0.0.1", "::1"}:
        raise ValueError("DATABASE_URL hostaddr must be loopback")
    if host in LOOPBACK:
        params["hostaddr"] = "::1" if host == "::1" else "127.0.0.1"
    params["connect_timeout"] = "5"
    return params


def _require_migration_128(conn) -> None:
    expected = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT checksum_sha256 FROM local_schema_migrations WHERE filename=%s",
            (MIGRATION.name,),
        )
        row = cur.fetchone()
        if not row or row[0] != expected:
            raise ValueError("exact migration 128 checksum is not applied; refusing import")
        cur.execute(
            """SELECT table_name,column_name FROM information_schema.columns
               WHERE table_schema=current_schema() AND (
                 (table_name='football_pool_issues' AND column_name IN
                    ('source_game_no','source_game_no_source'))
                 OR (table_name='football_pool_issue_matches' AND column_name IN
                    ('source_match_id','kickoff_date','kickoff_time_precision',
                     'kickoff_evidence','source_full_home_goals','source_full_away_goals',
                     'source_half_home_goals','source_half_away_goals',
                     'source_product_result_code','source_result_semantics_key',
                     'source_result_source','source_result_evidence'))
               )"""
        )
        columns = {(row[0], row[1]) for row in cur.fetchall()}
        expected_columns = {
            ("football_pool_issues", "source_game_no"),
            ("football_pool_issues", "source_game_no_source"),
            *{
                ("football_pool_issue_matches", name)
                for name in (
                    "source_match_id",
                    "kickoff_date",
                    "kickoff_time_precision",
                    "kickoff_evidence",
                    "source_full_home_goals",
                    "source_full_away_goals",
                    "source_half_home_goals",
                    "source_half_away_goals",
                    "source_product_result_code",
                    "source_result_semantics_key",
                    "source_result_source",
                    "source_result_evidence",
                )
            },
        }
        if columns != expected_columns:
            raise ValueError("migration 128 traditional fact columns are incomplete")


MEMBER_COLUMNS = (
    "match_order,match_id,source_match_id,league_name,home_team_name,away_team_name,"
    "kickoff_time,kickoff_date,kickoff_time_precision,kickoff_evidence,"
    "source_full_home_goals,source_full_away_goals,source_half_home_goals,"
    "source_half_away_goals,source_product_result_code,source_result_semantics_key,"
    "source_result_source,source_result_evidence,home_win_prob,draw_prob,away_win_prob,"
    "upset_score,public_heat_home,public_heat_draw,public_heat_away,fixture_id,"
    "identity_status,identity_evidence,source_raw_json"
)
MEMBER_KEYS = (
    "match_order",
    "match_id",
    "source_match_id",
    "league_name",
    "home_team_name",
    "away_team_name",
    "kickoff_time",
    "kickoff_date",
    "kickoff_time_precision",
    "kickoff_evidence",
    "source_full_home_goals",
    "source_full_away_goals",
    "source_half_home_goals",
    "source_half_away_goals",
    "source_product_result_code",
    "source_result_semantics_key",
    "source_result_source",
    "source_result_evidence",
    "home_win_prob",
    "draw_prob",
    "away_win_prob",
    "upset_score",
    "public_heat_home",
    "public_heat_draw",
    "public_heat_away",
    "fixture_id",
    "identity_status",
    "identity_evidence",
    "source_raw_json",
)
JSON_MEMBER_KEYS = {
    "kickoff_evidence",
    "source_result_evidence",
    "identity_evidence",
    "source_raw_json",
}


def _member_values(member: dict[str, Any], *, adapt_json: bool = False) -> tuple[Any, ...]:
    return tuple(
        Json(member[key]) if adapt_json and key in JSON_MEMBER_KEYS else member[key]
        for key in MEMBER_KEYS
    )


def _normalized_db_member(values: tuple[Any, ...]) -> tuple[Any, ...]:
    normalized = list(values)
    date_index = MEMBER_KEYS.index("kickoff_date")
    if normalized[date_index] is not None:
        normalized[date_index] = normalized[date_index].isoformat()
    return tuple(normalized)


def _normalized_timestamp(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:19]


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _normalized_team(value: str | None) -> str:
    return "".join((value or "").split())


def _json_mapping(value: Any, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"existing {field} must be a JSON object")
    return dict(value)


def _merge_import_evidence(
    existing: Any,
    *,
    namespace: str,
    payload: dict[str, Any],
    field: str,
) -> tuple[dict[str, Any], bool]:
    merged = _json_mapping(existing, field)
    old = merged.get(namespace)
    if old is not None and old != payload:
        raise ValueError(f"existing {field}.{namespace} conflicts with this source batch")
    if old == payload:
        return merged, False
    merged[namespace] = payload
    return merged, True


def _prepare_fill_member(existing: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """Return only source-fact columns to set after live identity checks."""
    label = f"slot {source['match_order']}"
    if existing["match_order"] != source["match_order"]:
        raise ValueError(f"existing {label} order differs from the history API")
    for side in ("home", "away"):
        field = f"{side}_team_name"
        if _normalized_team(existing.get(field)) != _normalized_team(source.get(field)):
            raise ValueError(f"existing {label} {side} team differs from the history API")

    expected_date = _as_date(source["kickoff_date"])
    if expected_date is None:
        raise ValueError(f"history API {label} has no kickoff date")
    stored_date = _as_date(existing.get("kickoff_date"))
    stored_legacy_date = _as_date(existing.get("kickoff_time"))
    if stored_date is not None and stored_date != expected_date:
        raise ValueError(f"existing {label} kickoff_date differs from the history API")
    if stored_legacy_date is not None and stored_legacy_date != expected_date:
        raise ValueError(f"existing {label} kickoff_time date differs from the history API")
    if stored_date is None and stored_legacy_date is None:
        raise ValueError(f"existing {label} has no date evidence for exact-slot revalidation")

    current_source_id = existing.get("source_match_id")
    incoming_source_id = source.get("source_match_id")
    if (
        current_source_id
        and incoming_source_id
        and str(current_source_id) != str(incoming_source_id)
    ):
        raise ValueError(f"existing {label} source_match_id conflicts with the history API")

    updates: dict[str, Any] = {}
    if stored_date is None:
        updates["kickoff_date"] = expected_date

    precision = existing.get("kickoff_time_precision") or "unknown"
    if precision == "unknown":
        # Keep a legacy kickoff_time intact for the resolver, while the precision
        # field prevents the catalog from presenting it as an exact kickoff.
        updates["kickoff_time_precision"] = "date_only"
    elif precision == "date_only":
        pass
    elif precision in {"minute", "second"}:
        if stored_legacy_date != expected_date:
            raise ValueError(f"existing {label} precise kickoff conflicts with the API date")
    else:
        raise ValueError(f"existing {label} has an unsupported kickoff precision")

    def fill_fact(field: str, incoming: Any) -> None:
        current = existing.get(field)
        if incoming is None:
            return
        if current is not None and current != incoming:
            raise ValueError(f"existing {label} {field} conflicts with the history API")
        if current is None:
            updates[field] = incoming

    if incoming_source_id and not current_source_id:
        updates["source_match_id"] = incoming_source_id
    for field in (
        "source_full_home_goals",
        "source_full_away_goals",
        "source_half_home_goals",
        "source_half_away_goals",
        "source_product_result_code",
        "source_result_semantics_key",
        "source_result_source",
    ):
        fill_fact(field, source.get(field))

    # An explicit '*' is evidence that the source has no settled full score;
    # it cannot coexist with a previously populated source-full score.
    source_raw = source.get("source_raw_json") or {}
    if source_raw.get("full_score_source_text") == "*":
        for field in ("source_full_home_goals", "source_full_away_goals"):
            if existing.get(field) is not None:
                raise ValueError(f"existing {label} {field} conflicts with API '*' marker")

    receipt = source_raw.get("import_receipt")
    if not isinstance(receipt, dict):
        raise ValueError(f"history API {label} is missing its import receipt")
    source_evidence = {
        "receipt": receipt,
        "evidence": source.get("kickoff_evidence") or {},
    }
    merged_kickoff, changed = _merge_import_evidence(
        existing.get("kickoff_evidence"),
        namespace="sporttery_history_import",
        payload=source_evidence,
        field="kickoff_evidence",
    )
    if changed:
        updates["kickoff_evidence"] = merged_kickoff

    result_evidence_payload = {
        "receipt": receipt,
        "evidence": source.get("source_result_evidence") or {},
    }
    merged_result, changed = _merge_import_evidence(
        existing.get("source_result_evidence"),
        namespace="sporttery_history_import",
        payload=result_evidence_payload,
        field="source_result_evidence",
    )
    if changed:
        updates["source_result_evidence"] = merged_result

    raw_source_without_receipt = {
        key: value for key, value in source_raw.items() if key != "import_receipt"
    }
    raw_payload = {"receipt": receipt, "source": raw_source_without_receipt}
    merged_raw, changed = _merge_import_evidence(
        existing.get("source_raw_json"),
        namespace="sporttery_history_import",
        payload=raw_payload,
        field="source_raw_json",
    )
    if changed:
        updates["source_raw_json"] = merged_raw
    return updates


def _pool_raw_hash(value: dict[str, Any]) -> str:
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()


def _fill_header_state_sha256(
    header: dict[str, Any], raw_without_import_marker: dict[str, Any]
) -> str:
    return _sha256(
        {
            "id": header.get("id"),
            "game_type": header.get("game_type"),
            "issue_no": header.get("issue_no"),
            "source_game_type": header.get("source_game_type"),
            "source_game_no": header.get("source_game_no"),
            "source_game_no_source": header.get("source_game_no_source"),
            "sale_start_time": _normalized_timestamp(header.get("sale_start_time")),
            "sale_stop_time": _normalized_timestamp(header.get("sale_stop_time")),
            "total_matches": header.get("total_matches"),
            "official_status": header.get("official_status"),
            "prize_pool_estimate": header.get("prize_pool_estimate"),
            "raw_json": raw_without_import_marker,
        }
    )


def _prepare_fill_header(existing: dict[str, Any], issue: dict[str, Any]) -> dict[str, Any]:
    label = f"{issue['game_type']}/{issue['issue_no']}"
    if existing["game_type"] != issue["game_type"] or existing["issue_no"] != issue["issue_no"]:
        raise ValueError(f"existing issue key differs for {label}")
    if existing.get("source_game_type") not in (None, issue["game_type"]):
        raise ValueError(f"existing {label} source game type conflicts")
    if existing.get("total_matches") != issue["total_matches"]:
        raise ValueError(f"existing {label} slot count differs from the history API")
    for field in ("source_game_no", "source_game_no_source"):
        current = existing.get(field)
        if current is not None and current != issue[field]:
            raise ValueError(f"existing {label} {field} conflicts with the history API")
    for field in ("sale_start_time", "sale_stop_time"):
        current = existing.get(field)
        incoming = issue[field]
        if current is not None and _normalized_timestamp(str(current)) != _normalized_timestamp(
            incoming
        ):
            raise ValueError(f"existing {label} {field} conflicts with the history API")

    raw = _json_mapping(existing.get("raw_json"), f"{label} raw_json")
    source_raw = issue.get("raw_json") or {}
    receipt = source_raw.get("import_receipt")
    if not isinstance(receipt, dict):
        raise ValueError(f"history API issue {label} is missing its import receipt")
    evidence = {key: value for key, value in source_raw.items() if key != "import_receipt"}
    old_marker = raw.get("traditional_history_import")
    raw_without_marker = {
        key: value for key, value in raw.items() if key != "traditional_history_import"
    }
    stored_raw_hash = existing.get("raw_hash")
    if old_marker is None:
        if stored_raw_hash is not None and stored_raw_hash != _pool_raw_hash(raw):
            raise ValueError(f"existing {label} raw_json hash is inconsistent")
    else:
        expected_marker = {
            "receipt": receipt,
            "evidence": evidence,
            "header_state_sha256": _fill_header_state_sha256(existing, raw_without_marker),
        }
        if stored_raw_hash != _pool_raw_hash(raw) or old_marker != expected_marker:
            raise ValueError(f"existing {label} header was modified after import")
        return {}

    updates: dict[str, Any] = {}
    if existing.get("source_game_type") is None:
        updates["source_game_type"] = issue["game_type"]
    if existing.get("source_game_no") is None:
        updates["source_game_no"] = issue["source_game_no"]
    if existing.get("source_game_no_source") is None:
        updates["source_game_no_source"] = issue["source_game_no_source"]
    if existing.get("sale_start_time") is None and issue.get("sale_start_time"):
        updates["sale_start_time"] = issue["sale_start_time"]
    if existing.get("sale_stop_time") is None and issue.get("sale_stop_time"):
        updates["sale_stop_time"] = issue["sale_stop_time"]
    projected_header = dict(existing)
    projected_header.update(
        {field: value for field, value in updates.items() if field not in {"raw_json", "raw_hash"}}
    )
    raw["traditional_history_import"] = {
        "receipt": receipt,
        "evidence": evidence,
        "header_state_sha256": _fill_header_state_sha256(projected_header, raw_without_marker),
    }
    updates["raw_json"] = raw
    updates["raw_hash"] = _pool_raw_hash(raw)
    return updates


def _already_imported(cur, issue: dict[str, Any], row: tuple[Any, ...]) -> bool:
    (
        issue_id,
        game_type,
        issue_no,
        source_game_type,
        source_game_no,
        source_game_no_source,
        sale_start,
        sale_stop,
        total,
        status,
        raw_hash,
        raw,
    ) = row
    receipt = (raw or {}).get("import_receipt", {})
    if receipt != {
        "contract": CONTRACT,
        "issue_sha256": issue["issue_sha256"],
        "manifest_sha256": issue["raw_json"]["import_receipt"]["manifest_sha256"],
    }:
        raise ValueError(
            f"existing {issue['game_type']}/{issue['issue_no']} is not this importer’s exact issue"
        )
    if (
        game_type != issue["game_type"]
        or issue_no != issue["issue_no"]
        or source_game_type != issue["source_game_type"]
        or source_game_no != issue["source_game_no"]
        or source_game_no_source != issue["source_game_no_source"]
        or _normalized_timestamp(sale_start) != _normalized_timestamp(issue["sale_start_time"])
        or _normalized_timestamp(sale_stop) != _normalized_timestamp(issue["sale_stop_time"])
        or total != issue["total_matches"]
        or status != issue["official_status"]
    ):
        raise ValueError(f"existing {issue['game_type']}/{issue['issue_no']} header was modified")
    actual_raw = _json_mapping(raw, f"{issue['game_type']}/{issue['issue_no']} raw_json")
    if (
        actual_raw != issue["raw_json"]
        or raw_hash != issue["raw_hash"]
        or raw_hash != _pool_raw_hash(actual_raw)
    ):
        raise ValueError(f"existing {issue['game_type']}/{issue['issue_no']} header was modified")
    cur.execute(
        f"SELECT {MEMBER_COLUMNS} FROM football_pool_issue_matches "
        "WHERE issue_id=%s ORDER BY match_order",
        (issue_id,),
    )
    actual = [_normalized_db_member(values) for values in cur.fetchall()]
    expected = [_member_values(member) for member in issue["matches"]]
    if actual != expected:
        raise ValueError(f"existing {issue['game_type']}/{issue['issue_no']} members were modified")
    return True


def _apply_fill_issue(cur, issue: dict[str, Any]) -> tuple[bool, int]:
    cur.execute(
        """SELECT id,game_type,issue_no,source_game_type,source_game_no,
                  source_game_no_source,sale_start_time::text,sale_stop_time::text,
                  total_matches,official_status,prize_pool_estimate::text,raw_hash,raw_json
           FROM football_pool_issues WHERE game_type=%s AND issue_no=%s FOR UPDATE""",
        (issue["game_type"], issue["issue_no"]),
    )
    row = cur.fetchone()
    if row is None:
        raise ValueError(
            f"{issue['game_type']}/{issue['issue_no']} disappeared after fill manifest creation"
        )
    header_keys = (
        "id",
        "game_type",
        "issue_no",
        "source_game_type",
        "source_game_no",
        "source_game_no_source",
        "sale_start_time",
        "sale_stop_time",
        "total_matches",
        "official_status",
        "prize_pool_estimate",
        "raw_hash",
        "raw_json",
    )
    header = dict(zip(header_keys, row, strict=True))
    header_updates = _prepare_fill_header(header, issue)

    cur.execute(
        f"SELECT id,{MEMBER_COLUMNS} FROM football_pool_issue_matches "
        "WHERE issue_id=%s ORDER BY match_order FOR UPDATE",
        (header["id"],),
    )
    member_rows = cur.fetchall()
    if len(member_rows) != len(issue["matches"]):
        raise ValueError(
            f"existing {issue['game_type']}/{issue['issue_no']} slot count changed after manifest creation"
        )
    planned_members: list[tuple[int, dict[str, Any]]] = []
    for db_row, source in zip(member_rows, issue["matches"], strict=True):
        membership_id = db_row[0]
        existing = dict(zip(MEMBER_KEYS, db_row[1:], strict=True))
        updates = _prepare_fill_member(existing, source)
        planned_members.append((membership_id, updates))

    changed = bool(header_updates) or any(updates for _, updates in planned_members)
    if header_updates:
        assignments = [f"{field}=%s" for field in header_updates]
        values = [
            Json(header_updates[field]) if field == "raw_json" else header_updates[field]
            for field in header_updates
        ]
        assignments.append("updated_at=now()")
        cur.execute(
            f"UPDATE football_pool_issues SET {','.join(assignments)} WHERE id=%s",
            (*values, header["id"]),
        )

    for membership_id, updates in planned_members:
        if not updates:
            continue
        assignments = [f"{field}=%s" for field in updates]
        values = [
            Json(updates[field]) if field in JSON_MEMBER_KEYS else updates[field]
            for field in updates
        ]
        cur.execute(
            f"UPDATE football_pool_issue_matches SET {','.join(assignments)} WHERE id=%s",
            (*values, membership_id),
        )
    return changed, sum(bool(updates) for _, updates in planned_members)


def apply_issue_batch(conn, batch: dict[str, Any]) -> dict[str, int]:
    operation = batch.get("issue_operation", "new")
    if operation not in {"new", "fill"}:
        raise ValueError(f"unsupported import operation: {operation}")
    if len(batch["issues"]) > 100:
        raise ValueError("an import transaction cannot exceed 100 issue keys")
    if any(issue.get("issue_operation") != operation for issue in batch["issues"]):
        raise ValueError("issue operation does not match the batch operation")
    if not batch["issues"]:
        if operation == "fill":
            return {"filled_issues": 0, "filled_members": 0, "already_filled_issues": 0}
        return {"inserted_issues": 0, "inserted_members": 0, "already_imported_issues": 0}
    from scripts.football_fixture_identity import IDENTITY_LOCK

    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
        cur.execute("SET LOCAL lock_timeout = '2s'")
        cur.execute("SET LOCAL statement_timeout = '90s'")
        cur.execute("SELECT pg_advisory_xact_lock(%s)", (IDENTITY_LOCK,))
        _require_migration_128(conn)
        if operation == "fill":
            filled_issues = filled_members = already_filled = 0
            for issue in batch["issues"]:
                changed, changed_members = _apply_fill_issue(cur, issue)
                if changed:
                    filled_issues += 1
                    filled_members += changed_members
                else:
                    already_filled += 1
            return {
                "filled_issues": filled_issues,
                "filled_members": filled_members,
                "already_filled_issues": already_filled,
            }
        inserted_issues = inserted_members = already_imported = 0
        for issue in batch["issues"]:
            cur.execute(
                """SELECT id,game_type,issue_no,source_game_type,source_game_no,
                          source_game_no_source,
                          sale_start_time::text,sale_stop_time::text,total_matches,
                          official_status,raw_hash,raw_json
                   FROM football_pool_issues WHERE game_type=%s AND issue_no=%s FOR UPDATE""",
                (issue["game_type"], issue["issue_no"]),
            )
            current = cur.fetchone()
            if current:
                if _already_imported(cur, issue, current):
                    already_imported += 1
                    continue
            cur.execute(
                """INSERT INTO football_pool_issues
                     (issue_no,game_type,source_game_type,source_game_no,source_game_no_source,
                      sale_start_time,sale_stop_time,total_matches,official_status,raw_hash,raw_json)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   RETURNING id""",
                (
                    issue["issue_no"],
                    issue["game_type"],
                    issue["source_game_type"],
                    issue["source_game_no"],
                    issue["source_game_no_source"],
                    issue["sale_start_time"],
                    issue["sale_stop_time"],
                    issue["total_matches"],
                    issue["official_status"],
                    issue["raw_hash"],
                    Json(issue["raw_json"]),
                ),
            )
            issue_id = cur.fetchone()[0]
            placeholders = ",".join(["%s"] * (len(MEMBER_KEYS) + 1))
            cur.executemany(
                f"INSERT INTO football_pool_issue_matches (issue_id,{MEMBER_COLUMNS}) "
                f"VALUES ({placeholders})",
                [
                    (issue_id, *_member_values(member, adapt_json=True))
                    for member in issue["matches"]
                ],
            )
            cur.execute(
                "SELECT count(*),min(match_order),max(match_order) "
                "FROM football_pool_issue_matches WHERE issue_id=%s",
                (issue_id,),
            )
            count, first_order, last_order = cur.fetchone()
            if (count, first_order, last_order) != (
                issue["total_matches"],
                1,
                issue["total_matches"],
            ):
                raise ValueError(
                    f"post-insert slot check failed for {issue['game_type']}/{issue['issue_no']}"
                )
            inserted_issues += 1
            inserted_members += count
    return {
        "inserted_issues": inserted_issues,
        "inserted_members": inserted_members,
        "already_imported_issues": already_imported,
    }


def main(argv: list[str] | None = None) -> int:
    default_preview, default_manifest, default_summary = default_input_paths()
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Defaults point to the dated API-complete planning snapshot. After any migration or "
            "production reconciliation, refresh the production inventory and regenerate all three "
            "input files before applying a batch."
        ),
    )
    parser.add_argument("--preview", type=Path, default=default_preview)
    parser.add_argument("--manifest", type=Path, default=default_manifest)
    parser.add_argument(
        "--manifest-summary",
        type=Path,
        default=default_summary,
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Candidate issue offset for bounded resume"
    )
    parser.add_argument(
        "--limit", type=int, default=25, help="At most 100 issue keys per transaction"
    )
    parser.add_argument(
        "--kind",
        choices=("new", "fill"),
        default="new",
        help="new missing issues or fill exact existing issues without replacing their identities",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply this bounded batch to an explicit local PostgreSQL target",
    )
    args = parser.parse_args(argv)

    batch = load_issue_batch(
        args.preview,
        args.manifest,
        args.manifest_summary,
        offset=args.offset,
        limit=args.limit,
        kind=args.kind,
    )
    report = {key: value for key, value in batch.items() if key != "issues"}
    report["mode"] = "apply" if args.apply else "plan"
    if args.apply and batch["issues"]:
        params = _local_database_parameters()
        with closing(psycopg2.connect(**params)) as conn, conn:
            report.update(apply_issue_batch(conn, batch))
    elif args.apply:
        if args.kind == "fill":
            report.update({"filled_issues": 0, "filled_members": 0, "already_filled_issues": 0})
        else:
            report.update(
                {"inserted_issues": 0, "inserted_members": 0, "already_imported_issues": 0}
            )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
