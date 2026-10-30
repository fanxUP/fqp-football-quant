"""Validate release evidence before applying pending production migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

REVIEWED_NO_BACKUP_CHECKSUMS = {
    "123_football_history_odds_invalid_timezone.sql": (
        "ba62d08357813c093a5304d9143c2e2c5e0295f010e4338afeb4d4ca65911744"
    ),
    "124_official_event_season_retention.sql": (
        "2f6de44205a6243737cb193c99ae0eaf0e011b66a8be6514388310a4c65f6d44"
    ),
    "125_football_fixture_identity.sql": (
        "9037dd6a91aca5c558b82b9aa41165f21bf4fe3f7a4fadfacdb8d3b7b0b91d10"
    ),
}
REVIEWED_NO_BACKUP_PAIR = [
    "124_official_event_season_retention.sql",
    "125_football_fixture_identity.sql",
]
NO_BACKUP_REHEARSAL_FIELD = "no_backup_migration_rehearsal"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _refuse(message: str) -> NoReturn:
    raise SystemExit(message)


def _verify_pinned_sql(project_root: Path, migration_names: list[str]) -> None:
    for name in migration_names:
        expected = REVIEWED_NO_BACKUP_CHECKSUMS[name]
        path = project_root / "sql" / name
        if not path.is_file():
            _refuse(f"Reviewed migration is missing from checkout: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            _refuse(f"Migration checksum is outside the reviewed no-backup release: {name}")


def _verify_no_backup_authorization(record: dict[str, Any]) -> None:
    if (
        record.get("no_backup_authorized") is not True
        or not str(record.get("no_backup_reason", "")).strip()
    ):
        _refuse("No-backup release requires explicit recorded operator authorization")
    if record.get("migration_transaction_dry_run") != "passed":
        _refuse("No-backup release requires a passed isolated migration transaction rehearsal")


def _verify_124_125_rehearsal(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    evidence_directory: Path | None,
) -> None:
    if record.get("migration_copy_dry_run") != "passed":
        _refuse("Migrations 124/125 require a passed isolated PostgreSQL migration copy rehearsal")
    manifest = record.get(NO_BACKUP_REHEARSAL_FIELD)
    if not isinstance(manifest, dict) or manifest.get("status") != "passed":
        _refuse("Migrations 124/125 require structured no-backup PostgreSQL rehearsal evidence")
    if evidence_directory is None:
        _refuse("No-backup rehearsal evidence directory is unavailable")
    report_name = manifest.get("report_path")
    if (
        not isinstance(report_name, str)
        or not report_name
        or Path(report_name).name != report_name
        or Path(report_name).is_absolute()
    ):
        _refuse("No-backup rehearsal report must be a sibling file of the release evidence")
    report_path = evidence_directory / report_name
    if report_path.is_symlink() or not report_path.is_file():
        _refuse("No-backup rehearsal detail report is missing or unsafe")
    report_bytes = report_path.read_bytes()
    if hashlib.sha256(report_bytes).hexdigest() != manifest.get("evidence_sha256"):
        _refuse("No-backup rehearsal detail report SHA-256 mismatch")
    try:
        report = json.loads(report_bytes)
    except json.JSONDecodeError as exc:
        raise SystemExit("No-backup rehearsal detail report is invalid JSON") from exc
    if not isinstance(report, dict) or report.get("status") != "passed":
        _refuse("No-backup rehearsal detail report is not marked passed")
    try:
        verified_at = datetime.fromisoformat(str(report.get("verified_at", "")))
    except ValueError as exc:
        raise SystemExit(
            "No-backup rehearsal report requires a valid verification timestamp"
        ) from exc
    if verified_at.tzinfo is None or not 0 <= (utc_now() - verified_at).total_seconds() <= 86400:
        _refuse("No-backup rehearsal report must be verified within the last 24 hours")
    if record.get("target_sha") != target_sha or report.get("target_sha") != target_sha:
        _refuse("No-backup migration rehearsal target SHA does not match the release target SHA")
    if manifest.get("pending_migrations") != pending or report.get("pending_migrations") != pending:
        _refuse("No-backup rehearsal pending migration set does not match the release plan")
    expected_checksums = {
        name: REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in REVIEWED_NO_BACKUP_PAIR
    }
    if manifest.get("sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    if report.get("migration_sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    database = report.get("database")
    if not isinstance(database, dict) or database.get("disposable") is not True:
        _refuse("No-backup rehearsal must run in a disposable isolated PostgreSQL database")
    if not isinstance(database.get("postgres_major"), int) or database["postgres_major"] < 15:
        _refuse("No-backup rehearsal must record a supported PostgreSQL major version")
    if (
        database.get("fixture_kind") != "synthetic_schema_fixture"
        or database.get("production_data_copy") is not False
    ):
        _refuse("No-backup rehearsal must disclose its synthetic fixture and production-copy scope")
    required_passes = (
        "existing_rows_preserved",
        "constraints_and_triggers_verified",
        "transaction_rollback_verified",
    )
    if any(report.get(field) != "passed" for field in required_passes):
        _refuse("No-backup rehearsal is missing isolation, preservation, schema, or rollback proof")
    timeouts = report.get("timeouts")
    if not isinstance(timeouts, dict) or timeouts.get("lock_seconds") != 2:
        _refuse("No-backup rehearsal must confirm the migrations' 2-second lock timeout")
    if timeouts.get("statement_seconds") != 30:
        _refuse("No-backup rehearsal must confirm the migrations' 30-second statement timeout")
    results = report.get("test_results")
    if not isinstance(results, dict) or not (
        type(results.get("passed")) is int
        and results["passed"] > 0
        and type(results.get("failed")) is int
        and results["failed"] == 0
        and type(results.get("skipped")) is int
        and results["skipped"] == 0
    ):
        _refuse("No-backup rehearsal must record executed passing tests with no failures or skips")


def _validate_no_backup(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    project_root: Path,
    evidence_directory: Path | None,
) -> None:
    _verify_no_backup_authorization(record)
    if pending == ["123_football_history_odds_invalid_timezone.sql"]:
        _verify_pinned_sql(project_root, pending)
        return
    if pending == REVIEWED_NO_BACKUP_PAIR:
        _verify_pinned_sql(project_root, pending)
        _verify_124_125_rehearsal(record, pending, target_sha, evidence_directory)
        return
    _refuse(
        "No-backup release is restricted to the pinned migration 123 or the exact reviewed 124+125 pair"
    )


def _validate_backup(record: dict[str, Any]) -> None:
    if record.get("migration_copy_dry_run") != "passed":
        _refuse("Pending migrations require a passed migration copy rehearsal")
    backup_path = record.get("backup_path")
    if not isinstance(backup_path, str) or not backup_path:
        _refuse("Pending migrations require a verified pre-deployment backup")
    backup = Path(backup_path)
    try:
        age = utc_now().timestamp() - backup.stat().st_mtime
    except OSError as exc:
        raise SystemExit("Pending migrations require an accessible pre-deployment backup") from exc
    if not 0 <= age <= 3600:
        _refuse("Pending migrations require a recent pre-deployment backup")
    with backup.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if checksum != record.get("backup_sha256"):
        _refuse("Backup checksum mismatch")
    try:
        subprocess.run(
            ["pg_restore", "--list", str(backup)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit("Backup archive validation failed") from exc


def validate_release_migrations(
    record: dict[str, Any],
    release_mode: str,
    pending: list[str],
    target_sha: str,
    *,
    project_root: Path,
    evidence_directory: Path | None = None,
) -> None:
    """Fail closed unless pending migrations meet the selected release policy."""
    if not pending:
        return
    if release_mode == "--apply-no-backup":
        _validate_no_backup(record, pending, target_sha, project_root, evidence_directory)
    elif release_mode == "--apply":
        _validate_backup(record)
    else:
        _refuse(f"Unsupported migration release mode: {release_mode}")


def validate_release_file(
    evidence_path: Path,
    release_mode: str,
    pending: list[str],
    target_sha: str,
    *,
    project_root: Path,
) -> None:
    try:
        record = json.loads(evidence_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Migration release evidence is unreadable") from exc
    if not isinstance(record, dict):
        _refuse("Migration release evidence must be a JSON object")
    validate_release_migrations(
        record,
        release_mode,
        pending,
        target_sha,
        project_root=project_root,
        evidence_directory=evidence_path.parent,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("release_mode", choices=("apply", "apply-no-backup"))
    parser.add_argument("pending_json")
    parser.add_argument("target_sha")
    args = parser.parse_args()
    try:
        pending = json.loads(args.pending_json)
    except json.JSONDecodeError as exc:
        parser.error(f"pending migration list is invalid JSON: {exc}")
    if not isinstance(pending, list) or any(not isinstance(name, str) for name in pending):
        parser.error("pending migration list must be a JSON array of filenames")
    validate_release_file(
        args.evidence,
        f"--{args.release_mode}",
        pending,
        args.target_sha,
        project_root=Path.cwd(),
    )
    print("Migration release policy passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
