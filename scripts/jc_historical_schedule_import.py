"""Append-only import of vetted, schedule-only historical JC candidates.

The ordinary official storage path is an upsert and is deliberately not used
here. A batch either inserts its eligible rows in one transaction or rolls the
whole transaction back; existing keys are classified and left untouched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import Json

from scripts.official_history_importer import derive_business_date_from_match_date

EXPECTED_ARTIFACT = "football-jc-schedule-import-candidate-manifest/v2"
EXPECTED_NAMESPACE = "titan007.lottery_matches"
EXPECTED_SCOPE_PREFIX = "JC schedule rows only;"
EXPECTED_DATE_RULE = "official_code_weekday_on_or_before_source_match_date"
OFFICIAL_CODE_RE = re.compile(r"^周([一二三四五六日])([0-9]{3})$")
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,95}$")
MAX_BATCH_SIZE = 500
ADVISORY_LOCK_KEY = (1718584146, 20261113)
_CANDIDATE_VALIDATION_TOKEN = object()

CSV_FIELDS = (
    "source_namespace",
    "lottery_match_id",
    "source_match_date",
    "business_date",
    "official_match_code",
    "league_source_id",
    "league_name",
    "home_source_team_id",
    "home_team",
    "home_full_name",
    "away_source_team_id",
    "away_team",
    "away_full_name",
    "linked_titan_match_id",
    "link_method",
    "titan_match_date",
    "titan_kickoff_local_candidate",
    "titan_timezone",
    "mapped_home_titan_team_id",
    "mapped_away_titan_team_id",
    "mapped_team_ids_match",
    "direct_jc_code_matches",
    "linked_titan_id_unique",
    "readiness",
)

COUNT_KEYS = (
    "planned_insert",
    "inserted",
    "already_present",
    "source_id_conflict",
    "official_key_conflict",
    "split_key_conflict",
    "outside_retention_window",
)


class CandidateFileError(ValueError):
    """The source file or manifest does not satisfy the approved import contract."""


@dataclass(frozen=True)
class Candidate:
    source_match_id: str
    business_date: date
    source_match_date: date
    official_match_code: str
    league_source_id: str
    league_name: str
    home_source_team_id: str
    home_team: str
    home_full_name: str
    away_source_team_id: str
    away_team: str
    away_full_name: str
    linked_titan_match_id: str
    link_method: str
    titan_match_date: date
    kickoff_time: datetime
    titan_timezone: str
    mapped_home_titan_team_id: str
    mapped_away_titan_team_id: str
    readiness: str


@dataclass(frozen=True)
class CandidateFile:
    csv_path: Path
    manifest_path: Path
    csv_sha256: str
    approved_csv_sha256: str
    cutoff_inclusive: date
    candidates: tuple[Candidate, ...]
    _validation_token: object | None = field(default=None, repr=False, compare=False)
    _validated_candidates_sha256: str = field(default="", repr=False, compare=False)


def _truthy(value: str) -> bool:
    return value.strip().lower() == "true"


def _positive_id(value: str, field: str, row_number: int) -> str:
    normalized = value.strip()
    if not normalized.isdecimal() or int(normalized) <= 0:
        raise CandidateFileError(f"row {row_number}: invalid positive {field}")
    return normalized


def _validate_row(row: dict[str, str], row_number: int, cutoff: date) -> Candidate:
    if row.get("source_namespace", "").strip() != EXPECTED_NAMESPACE:
        raise CandidateFileError(f"row {row_number}: unexpected source namespace")

    source_id = _positive_id(row.get("lottery_match_id", ""), "lottery_match_id", row_number)
    titan_id = _positive_id(
        row.get("linked_titan_match_id", ""), "linked_titan_match_id", row_number
    )
    try:
        source_match_date = date.fromisoformat(row.get("source_match_date", "").strip())
        business_date = date.fromisoformat(row.get("business_date", "").strip())
        titan_date = date.fromisoformat(row.get("titan_match_date", "").strip())
        kickoff = datetime.strptime(
            row.get("titan_kickoff_local_candidate", "").strip(), "%Y-%m-%d %H:%M"
        )
    except ValueError as exc:
        raise CandidateFileError(f"row {row_number}: invalid candidate date/time") from exc
    if source_match_date > cutoff:
        raise CandidateFileError(f"row {row_number}: source match date exceeds manifest cutoff")
    if titan_date != source_match_date:
        raise CandidateFileError(
            f"row {row_number}: Titan match date differs from source match date"
        )
    if row.get("titan_timezone", "").strip() != "Asia/Shanghai":
        raise CandidateFileError(f"row {row_number}: unsupported Titan time zone")

    code = row.get("official_match_code", "").strip()
    code_match = OFFICIAL_CODE_RE.fullmatch(code)
    if not code_match:
        raise CandidateFileError(f"row {row_number}: invalid Sporttery match code")
    # The source column is the Sporttery/Titan matchDate calendar date, not
    # always the ticket business date. Late kickoffs can be assigned to the
    # previous weekday's lottery code; use the same rule as official history.
    business_date_text = derive_business_date_from_match_date(source_match_date.isoformat(), code)
    if not business_date_text:
        raise CandidateFileError(f"row {row_number}: cannot derive official business date")
    if date.fromisoformat(business_date_text) != business_date:
        raise CandidateFileError(
            f"row {row_number}: business date differs from official derivation"
        )

    for required_field in (
        "league_name",
        "home_team",
        "away_team",
        "home_full_name",
        "away_full_name",
    ):
        if not row.get(required_field, "").strip():
            raise CandidateFileError(f"row {row_number}: missing {required_field}")
    if any(
        len(row[field].strip()) > maximum
        for field, maximum in (("league_name", 128), ("home_team", 128), ("away_team", 128))
    ):
        raise CandidateFileError(f"row {row_number}: display value exceeds database length")
    if not _truthy(row.get("linked_titan_id_unique", "")):
        raise CandidateFileError(f"row {row_number}: linked Titan match ID is not unique")

    readiness = row.get("readiness", "").strip()
    if readiness == "mapped_team_ids_date_time_candidate":
        if not _truthy(row.get("mapped_team_ids_match", "")):
            raise CandidateFileError(f"row {row_number}: mapped-team proof is incomplete")
        mapped_home = _positive_id(
            row.get("mapped_home_titan_team_id", ""), "mapped home team ID", row_number
        )
        mapped_away = _positive_id(
            row.get("mapped_away_titan_team_id", ""), "mapped away team ID", row_number
        )
        if mapped_home == mapped_away:
            raise CandidateFileError(f"row {row_number}: mapped home and away IDs are equal")
    elif readiness == "direct_code_date_time_candidate":
        if not _truthy(row.get("direct_jc_code_matches", "")):
            raise CandidateFileError(f"row {row_number}: direct-code proof is incomplete")
    else:
        raise CandidateFileError(
            f"row {row_number}: candidate is outside the admitted readiness classes"
        )

    return Candidate(
        source_match_id=source_id,
        business_date=business_date,
        source_match_date=source_match_date,
        official_match_code=code,
        league_source_id=row.get("league_source_id", "").strip(),
        league_name=row["league_name"].strip(),
        home_source_team_id=row.get("home_source_team_id", "").strip(),
        home_team=row["home_team"].strip(),
        home_full_name=row["home_full_name"].strip(),
        away_source_team_id=row.get("away_source_team_id", "").strip(),
        away_team=row["away_team"].strip(),
        away_full_name=row["away_full_name"].strip(),
        linked_titan_match_id=titan_id,
        link_method=row.get("link_method", "").strip(),
        titan_match_date=titan_date,
        kickoff_time=kickoff,
        titan_timezone=row["titan_timezone"].strip(),
        mapped_home_titan_team_id=row.get("mapped_home_titan_team_id", "").strip(),
        mapped_away_titan_team_id=row.get("mapped_away_titan_team_id", "").strip(),
        readiness=readiness,
    )


def _candidate_fingerprint(candidates: tuple[Candidate, ...]) -> str:
    normalized = [
        {
            field_name: (value.isoformat() if isinstance(value, (date, datetime)) else value)
            for field_name, value in vars(candidate).items()
        }
        for candidate in candidates
    ]
    payload = json.dumps(
        normalized,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_candidate_file(
    csv_path: Path,
    manifest_path: Path,
    *,
    expected_csv_sha256: str,
) -> CandidateFile:
    """Load the exact schedule-only artifact and verify every row before use."""
    csv_path = Path(csv_path)
    manifest_path = Path(manifest_path)
    approved_hash = str(expected_csv_sha256).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", approved_hash):
        raise CandidateFileError("independently approved CSV SHA-256 is invalid")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        raw_csv = csv_path.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateFileError("cannot read candidate CSV or manifest") from exc
    if manifest.get("artifact") != EXPECTED_ARTIFACT:
        raise CandidateFileError("unexpected candidate manifest artifact")
    if not str(manifest.get("scope", "")).startswith(EXPECTED_SCOPE_PREFIX):
        raise CandidateFileError("manifest scope is not schedule-only")
    if manifest.get("business_date_rule") != EXPECTED_DATE_RULE:
        raise CandidateFileError("manifest does not declare the official business-date derivation")

    actual_hash = hashlib.sha256(raw_csv).hexdigest()
    if actual_hash != approved_hash:
        raise CandidateFileError("candidate CSV does not match independently approved SHA-256")
    expected_hash = str(manifest.get("csv_sha256", "")).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash) or actual_hash != expected_hash:
        raise CandidateFileError("candidate CSV SHA-256 does not match manifest")
    try:
        cutoff = date.fromisoformat(str(manifest["cutoff_inclusive"]))
        expected_count = int(manifest["candidate_rows"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CandidateFileError("manifest cutoff or row count is invalid") from exc
    if expected_count < 1:
        raise CandidateFileError("manifest contains no candidates")

    try:
        with csv_path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            if tuple(reader.fieldnames or ()) != CSV_FIELDS:
                raise CandidateFileError(
                    "candidate CSV columns do not match schedule-only contract"
                )
            candidates = tuple(
                _validate_row(row, index, cutoff) for index, row in enumerate(reader, start=2)
            )
    except OSError as exc:
        raise CandidateFileError("cannot read candidate CSV") from exc
    if len(candidates) != expected_count:
        raise CandidateFileError("candidate row count does not match manifest")
    if len({candidate.source_match_id for candidate in candidates}) != len(candidates):
        raise CandidateFileError("candidate source MatchId values are not unique")
    if len(
        {(candidate.business_date, candidate.official_match_code) for candidate in candidates}
    ) != len(candidates):
        raise CandidateFileError("candidate business-date/match-code keys are not unique")
    return CandidateFile(
        csv_path=csv_path,
        manifest_path=manifest_path,
        csv_sha256=actual_hash,
        approved_csv_sha256=approved_hash,
        cutoff_inclusive=cutoff,
        candidates=candidates,
        _validation_token=_CANDIDATE_VALIDATION_TOKEN,
        _validated_candidates_sha256=_candidate_fingerprint(candidates),
    )


def _existing_matches(cur: Any, candidates: tuple[Candidate, ...]) -> dict[str, tuple[Any, Any]]:
    identities = [
        {
            "source_match_id": item.source_match_id,
            "business_date": item.business_date.isoformat(),
            "official_match_code": item.official_match_code,
        }
        for item in candidates
    ]
    cur.execute(
        """WITH wanted AS (
               SELECT source_match_id,business_date,official_match_code
               FROM jsonb_to_recordset(%s::jsonb) AS x(
                   source_match_id text,business_date date,official_match_code text
               )
           )
           SELECT w.source_match_id,w.business_date,w.official_match_code,
                  src.id,src.source_match_id,src.business_date,src.official_match_code,
                  key.id,key.source_match_id,key.business_date,key.official_match_code
           FROM wanted w
           LEFT JOIN official_matches src ON src.source_match_id=w.source_match_id
           LEFT JOIN official_matches key
             ON key.business_date=w.business_date
            AND key.official_match_code=w.official_match_code""",
        (json.dumps(identities, separators=(",", ":")),),
    )
    return {
        row[0]: (
            None if row[3] is None else {"id": row[3], "source_match_id": row[4]},
            None if row[7] is None else {"id": row[7], "source_match_id": row[8]},
        )
        for row in cur.fetchall()
    }


def _retained_windows(cur: Any) -> dict[str, list[tuple[date, date]]]:
    cur.execute(
        """SELECT to_regclass('official_event_season_retention'),
                  to_regclass('official_event_season_targets')"""
    )
    retention_table, targets_table = cur.fetchone()
    table = (
        "official_event_season_retention"
        if retention_table
        else ("official_event_season_targets" if targets_table else None)
    )
    if table is None:
        raise RuntimeError("official season retention window table is missing or empty")
    cur.execute(f"SELECT league_name,season_start_date,season_end_date FROM {table}")
    windows: dict[str, list[tuple[date, date]]] = {}
    for league, start, end in cur.fetchall():
        windows.setdefault(str(league), []).append((start, end))
    if not windows:
        raise RuntimeError("official season retention window table is missing or empty")
    return windows


def _classify(source_hit: dict[str, Any] | None, key_hit: dict[str, Any] | None) -> str:
    if source_hit and key_hit:
        return "already_present" if source_hit["id"] == key_hit["id"] else "split_key_conflict"
    if source_hit:
        return "source_id_conflict"
    if key_hit:
        return "official_key_conflict"
    return "planned_insert"


def _raw_evidence(candidate: Candidate, artifact: CandidateFile, batch_id: str) -> dict[str, Any]:
    return {
        "source": "titan007_historical_jc_schedule_backfill",
        "matchId": candidate.source_match_id,
        "backfill": {
            "batch_id": batch_id,
            "candidate_csv_sha256": artifact.csv_sha256,
            "cutoff_inclusive": artifact.cutoff_inclusive.isoformat(),
            "source_namespace": EXPECTED_NAMESPACE,
            "source_match_id": candidate.source_match_id,
            "source_row": {"lottery_match_id": candidate.source_match_id},
            "identity": {
                "business_date": candidate.business_date.isoformat(),
                "source_match_date": candidate.source_match_date.isoformat(),
                "official_match_code": candidate.official_match_code,
                "league_source_id": candidate.league_source_id,
                "league_name": candidate.league_name,
                "home_name": candidate.home_team,
                "home_full_name": candidate.home_full_name,
                "away_name": candidate.away_team,
                "away_full_name": candidate.away_full_name,
            },
            "kickoff_evidence": {
                "provider": "Titan007",
                "linked_match_id": candidate.linked_titan_match_id,
                "match_date": candidate.titan_match_date.isoformat(),
                "kickoff_local_candidate": candidate.kickoff_time.isoformat(sep=" "),
                "timezone": candidate.titan_timezone,
                "link_method": candidate.link_method,
                "readiness_class": candidate.readiness,
            },
            "team_mapping": {
                "home_source_team_id": candidate.home_source_team_id,
                "home_titan_team_id": candidate.mapped_home_titan_team_id,
                "away_source_team_id": candidate.away_source_team_id,
                "away_titan_team_id": candidate.mapped_away_titan_team_id,
            },
            "match_status_evidence": "not_supplied",
            "sale_stop_time_evidence": "not_supplied",
            "results_imported": False,
            "odds_imported": False,
        },
    }


def import_schedule_batch(
    conn: Any,
    artifact: CandidateFile,
    *,
    batch_id: str,
    offset: int,
    limit: int,
    apply: bool = False,
) -> dict[str, Any]:
    """Preview or atomically insert one bounded candidate batch.

    Existing rows are never changed. A database exception during an applied
    batch rolls back every insertion in that transaction.
    """
    if not BATCH_ID_RE.fullmatch(batch_id):
        raise ValueError("batch_id must be 3-96 safe ASCII characters")
    if type(offset) is not int or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    if type(limit) is not int or not 1 <= limit <= MAX_BATCH_SIZE:
        raise ValueError(f"limit must be between 1 and {MAX_BATCH_SIZE}")
    if conn.get_transaction_status() != psycopg2.extensions.TRANSACTION_STATUS_IDLE:
        raise RuntimeError("import requires an idle connection and owns its transaction")
    if apply:
        if (
            artifact._validation_token is not _CANDIDATE_VALIDATION_TOKEN
            or _candidate_fingerprint(artifact.candidates) != artifact._validated_candidates_sha256
        ):
            raise RuntimeError("apply requires an unmodified loader-validated candidate artifact")
        if artifact.approved_csv_sha256 != artifact.csv_sha256:
            raise RuntimeError("apply requires an independently approved SHA-256 matching the CSV")
        try:
            current_csv_sha256 = hashlib.sha256(artifact.csv_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise RuntimeError("apply candidate CSV is no longer readable") from exc
        if current_csv_sha256 != artifact.approved_csv_sha256:
            raise RuntimeError("apply candidate CSV changed after validation")

    selected = artifact.candidates[offset : offset + limit]
    counts = dict.fromkeys(COUNT_KEYS, 0)
    if not selected:
        return {
            "status": "dry_run" if not apply else "applied",
            "batch_id": batch_id,
            "candidate_csv_sha256": artifact.csv_sha256,
            "cutoff_inclusive": artifact.cutoff_inclusive.isoformat(),
            "offset": offset,
            "requested": 0,
            "counts": counts,
        }

    try:
        with conn.cursor() as cur:
            cur.execute("BEGIN ISOLATION LEVEL SERIALIZABLE")
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute("SET LOCAL statement_timeout = '30s'")
            cur.execute("SELECT pg_advisory_xact_lock(%s,%s)", ADVISORY_LOCK_KEY)
            exists = _existing_matches(cur, selected)
            windows = _retained_windows(cur)
            outcomes: list[tuple[Candidate, str]] = []
            for candidate in selected:
                source_hit, key_hit = exists[candidate.source_match_id]
                status = _classify(source_hit, key_hit)
                if status == "planned_insert" and not any(
                    start <= candidate.business_date <= end
                    for start, end in windows.get(candidate.league_name, [])
                ):
                    status = "outside_retention_window"
                outcomes.append((candidate, status))
                counts[status] += 1

            if apply:
                for candidate, status in outcomes:
                    if status != "planned_insert":
                        continue
                    raw = _raw_evidence(candidate, artifact, batch_id)
                    serialized = json.dumps(
                        raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")
                    )
                    cur.execute(
                        """INSERT INTO official_matches (
                               sport_type,business_date,official_match_code,source_match_id,
                               league_name,home_team_name,away_team_name,kickoff_time,
                               sale_stop_time,sale_status,match_status,source_url,raw_hash,
                               raw_json,updated_at
                           ) VALUES (
                               'football',%(business_date)s,%(official_match_code)s,
                               %(source_match_id)s,%(league_name)s,%(home_team_name)s,
                               %(away_team_name)s,%(kickoff_time)s,NULL,'unknown','unknown',
                               NULL,%(raw_hash)s,%(raw_json)s,now()
                           ) RETURNING id""",
                        {
                            "business_date": candidate.business_date,
                            "official_match_code": candidate.official_match_code,
                            "source_match_id": candidate.source_match_id,
                            "league_name": candidate.league_name,
                            "home_team_name": candidate.home_team,
                            "away_team_name": candidate.away_team,
                            "kickoff_time": candidate.kickoff_time,
                            "raw_hash": hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                            "raw_json": Json(
                                raw,
                                dumps=lambda value: json.dumps(
                                    value, ensure_ascii=False, separators=(",", ":")
                                ),
                            ),
                        },
                    )
                    cur.fetchone()
                    counts["inserted"] += 1
                counts["planned_insert"] = 0
            if apply:
                conn.commit()
            else:
                conn.rollback()
    except Exception:
        conn.rollback()
        raise

    return {
        "status": "applied" if apply else "dry_run",
        "batch_id": batch_id,
        "candidate_csv_sha256": artifact.csv_sha256,
        "cutoff_inclusive": artifact.cutoff_inclusive.isoformat(),
        "offset": offset,
        "requested": len(selected),
        "counts": counts,
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument(
        "--expected-csv-sha256",
        required=True,
        help="independently reviewed SHA-256 of the exact candidate CSV",
    )
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="commit eligible rows")
    parser.add_argument(
        "--confirm-production-writes",
        action="store_true",
        help="required together with --apply to acknowledge persistent database writes",
    )
    args = parser.parse_args()
    if args.apply != args.confirm_production_writes:
        parser.error("--apply and --confirm-production-writes must be supplied together")
    dsn = os.environ.get("FQP_JC_HISTORY_IMPORT_DSN", "").strip()
    if not dsn:
        parser.error("FQP_JC_HISTORY_IMPORT_DSN is required; DATABASE_URL is intentionally ignored")
    try:
        artifact = load_candidate_file(
            args.csv,
            args.manifest,
            expected_csv_sha256=args.expected_csv_sha256,
        )
        with psycopg2.connect(dsn, connect_timeout=5) as conn:
            result = import_schedule_batch(
                conn,
                artifact,
                batch_id=args.batch_id,
                offset=args.offset,
                limit=args.limit,
                apply=args.apply,
            )
    except (CandidateFileError, ValueError, psycopg2.Error, RuntimeError) as exc:
        print(
            json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
