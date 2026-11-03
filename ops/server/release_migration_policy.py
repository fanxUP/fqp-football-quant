"""Validate release evidence before applying pending production migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

REVIEWED_NO_BACKUP_CHECKSUMS = {
    "127_football_fixture_seasons.sql": (
        "7c0c61920f62680e3f4951e5dd98dd57a9588f12315df1e64c570f69d725023c"
    ),
    "123_football_history_odds_invalid_timezone.sql": (
        "ba62d08357813c093a5304d9143c2e2c5e0295f010e4338afeb4d4ca65911744"
    ),
    "124_official_event_season_retention.sql": (
        "2f6de44205a6243737cb193c99ae0eaf0e011b66a8be6514388310a4c65f6d44"
    ),
    "125_football_fixture_identity.sql": (
        "9037dd6a91aca5c558b82b9aa41165f21bf4fe3f7a4fadfacdb8d3b7b0b91d10"
    ),
    "126_official_season_retention_access.sql": (
        "dc3dd7640d261eb625ecb8f4fc8a26c3562a55ffd52b99c2c54fd4d23d695ff8"
    ),
    "128_traditional_history_facts.sql": (
        "072bb16f074926911fdcb5972575dc95795e26e096c079dec1a558a64cddd9d2"
    ),
    "129_football_fixture_identity_aliases.sql": (
        "ee124b135697aa5cce79f37d9ebf7c8d96e6e4ee64918aabd3e856b4bc4e4f58"
    ),
    "130_football_fixture_result_facts.sql": (
        "be4c70ac5a61b0a3047e62dd89be7dff57bd58a16587958905284e712b671655"
    ),
    "131_prediction_statistics_rollup.sql": (
        "a98300da5bfa7ec8b1e1c21cabec83ec580a4346cb6e6835707d831706c55b1f"
    ),
}
REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS = {
    "131_prediction_statistics_rollup.down.sql": (
        "2b99a556dccf22e7ae181cd9a8bb9232385338483f3bf91180839e6a0329e4c3"
    )
}
REVIEWED_NO_BACKUP_SEASONS = ["127_football_fixture_seasons.sql"]
REVIEWED_NO_BACKUP_PAIR = [
    "124_official_event_season_retention.sql",
    "125_football_fixture_identity.sql",
]
REVIEWED_NO_BACKUP_ACL = ["126_official_season_retention_access.sql"]
REVIEWED_NO_BACKUP_TRADITIONAL_FACTS = ["128_traditional_history_facts.sql"]
REVIEWED_NO_BACKUP_ALIASES = ["129_football_fixture_identity_aliases.sql"]
REVIEWED_NO_BACKUP_RESULT_FACTS = ["130_football_fixture_result_facts.sql"]
REVIEWED_NO_BACKUP_PREDICTION_STATS = ["131_prediction_statistics_rollup.sql"]
NO_BACKUP_REHEARSAL_FIELD = "no_backup_migration_rehearsal"
MAX_PRODUCTION_SAMPLE_MATCHES = 20
MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE = 250_000
TRUSTED_NO_BACKUP_SIGNER_PUBLIC_KEY = Path("/etc/ssh/ssh_host_ed25519_key.pub")
TRUSTED_SSH_KEYGEN = Path("/usr/bin/ssh-keygen")
NO_BACKUP_SIGNER_IDENTITY = "fqp-production-host"
NO_BACKUP_SIGNING_NAMESPACE = "fqp-p107-migration-131"


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


def _verify_pinned_rollback_sql(project_root: Path, rollback_names: list[str]) -> None:
    for name in rollback_names:
        expected = REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS[name]
        path = project_root / "sql" / "down" / name
        if not path.is_file():
            _refuse(f"Reviewed rollback migration is missing from checkout: {name}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            _refuse(
                f"Rollback migration checksum is outside the reviewed no-backup release: {name}"
            )


def _verify_signed_rehearsal(report_path: Path, report_bytes: bytes) -> None:
    signature_path = Path(f"{report_path}.sig")
    public_key_path = TRUSTED_NO_BACKUP_SIGNER_PUBLIC_KEY
    if (
        signature_path.is_symlink()
        or not signature_path.is_file()
        or public_key_path.is_symlink()
        or not public_key_path.is_file()
        or TRUSTED_SSH_KEYGEN.is_symlink()
        or not TRUSTED_SSH_KEYGEN.is_file()
        or not TRUSTED_SSH_KEYGEN.stat().st_mode & 0o111
    ):
        _refuse("Prediction statistics rehearsal requires a signed report from the production host")
    try:
        public_key_parts = public_key_path.read_text().strip().split()
    except OSError as exc:
        raise SystemExit("Cannot read the trusted production-host signing key") from exc
    if len(public_key_parts) < 2 or public_key_parts[0] != "ssh-ed25519":
        _refuse("Trusted production-host signing key is invalid")

    with tempfile.TemporaryDirectory(prefix="fqp-rehearsal-signers-") as temp_directory:
        allowed_signers = Path(temp_directory) / "allowed_signers"
        allowed_signers.write_text(
            f"{NO_BACKUP_SIGNER_IDENTITY} {public_key_parts[0]} {public_key_parts[1]}\n"
        )
        try:
            result = subprocess.run(
                [
                    str(TRUSTED_SSH_KEYGEN),
                    "-Y",
                    "verify",
                    "-f",
                    str(allowed_signers),
                    "-I",
                    NO_BACKUP_SIGNER_IDENTITY,
                    "-n",
                    NO_BACKUP_SIGNING_NAMESPACE,
                    "-s",
                    str(signature_path),
                ],
                input=report_bytes,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SystemExit("Cannot verify the production-host rehearsal signature") from exc
    if result.returncode:
        _refuse(
            "Prediction statistics rehearsal signature is invalid or not from the production host"
        )


def _verify_no_backup_authorization(record: dict[str, Any]) -> None:
    if (
        record.get("no_backup_authorized") is not True
        or not str(record.get("no_backup_reason", "")).strip()
    ):
        _refuse("No-backup release requires explicit recorded operator authorization")
    if record.get("migration_transaction_dry_run") != "passed":
        _refuse("No-backup release requires a passed isolated migration transaction rehearsal")


def _verify_no_backup_rehearsal(
    record: dict[str, Any],
    pending: list[str],
    target_sha: str,
    evidence_directory: Path | None,
) -> None:
    if record.get("migration_copy_dry_run") != "passed":
        _refuse("Reviewed migrations require a passed isolated PostgreSQL migration copy rehearsal")
    manifest = record.get(NO_BACKUP_REHEARSAL_FIELD)
    if not isinstance(manifest, dict) or manifest.get("status") != "passed":
        _refuse("Reviewed migrations require structured no-backup PostgreSQL rehearsal evidence")
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
    if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS:
        _verify_signed_rehearsal(report_path, report_bytes)
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
    expected_checksums = {name: REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in pending}
    if manifest.get("sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    if report.get("migration_sha256") != expected_checksums:
        _refuse("No-backup rehearsal checksums do not match the reviewed migration set")
    database = report.get("database")
    if not isinstance(database, dict) or database.get("disposable") is not True:
        _refuse("No-backup rehearsal must run in a disposable isolated PostgreSQL database")
    if not isinstance(database.get("postgres_major"), int) or database["postgres_major"] < 15:
        _refuse("No-backup rehearsal must record a supported PostgreSQL major version")
    expected_fixture_kind = (
        "targeted_production_schema_data_copy"
        if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS
        else "synthetic_schema_fixture"
    )
    expected_production_copy = pending == REVIEWED_NO_BACKUP_PREDICTION_STATS
    if (
        database.get("fixture_kind") != expected_fixture_kind
        or database.get("production_data_copy") is not expected_production_copy
    ):
        _refuse("No-backup rehearsal must disclose its required fixture and production-copy scope")
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
    if pending == REVIEWED_NO_BACKUP_ACL:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_retention_table") is not False
        ):
            _refuse(
                "ACL repair rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_business_paths",
                "acl_rollback_verified",
            )
        ):
            _refuse(
                "ACL repair requires runtime grants, application business paths and ACL rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_SEASONS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_season_identity_tables") is not False
        ):
            _refuse(
                "Season identity rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_business_paths",
                "acl_rollback_verified",
            )
        ):
            _refuse(
                "Season identity requires application ACL, business paths and ACL rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_TRADITIONAL_FACTS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
        ):
            _refuse(
                "Traditional history rehearsal must use the restricted non-superuser fqp application role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_catalog_access",
                "application_catalog_read_path",
                "application_import_write_path",
            )
        ):
            _refuse(
                "Traditional history requires runtime-role catalog access, catalog read and import write proof"
            )

    if pending == REVIEWED_NO_BACKUP_ALIASES:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_alias_table") is not False
        ):
            _refuse(
                "Fixture alias rehearsal must use the restricted non-owner application runtime role"
            )
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "application_alias_insert_and_read_path",
                "application_alias_rollback_verified",
            )
        ):
            _refuse(
                "Fixture alias migration requires runtime ACL, alias read/write path and rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_RESULT_FACTS:
        role = report.get("application_role")
        if (
            not isinstance(role, dict)
            or role.get("name") != "fqp"
            or role.get("superuser") is not False
            or role.get("owns_result_fact_table") is not False
        ):
            _refuse("Result fact rehearsal must use the restricted non-owner fqp runtime role")
        if any(
            report.get(field) != "passed"
            for field in (
                "application_role_acl",
                "result_fact_insert_and_model_read",
                "source_fixture_mismatch_rejected",
                "append_only_enforced",
                "result_fact_rollback_verified",
            )
        ):
            _refuse(
                "Result fact migration requires runtime ACL, source binding, model read and rollback proof"
            )

    if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS:
        _verify_prediction_statistics_rehearsal(report)


def _verify_prediction_statistics_rehearsal(report: dict[str, Any]) -> None:
    database = report["database"]
    schema_sha256 = database.get("schema_sha256")
    source_revision = database.get("source_revision")
    production_copy_at = database.get("production_copy_at")
    if (
        not isinstance(schema_sha256, str)
        or len(schema_sha256) != 64
        or any(character not in "0123456789abcdef" for character in schema_sha256)
        or not isinstance(source_revision, str)
        or len(source_revision) != 40
        or any(character not in "0123456789abcdef" for character in source_revision)
    ):
        _refuse(
            "Prediction statistics rehearsal requires production schema and source revision fingerprints"
        )
    try:
        copied_at = datetime.fromisoformat(str(production_copy_at))
    except ValueError as exc:
        raise SystemExit(
            "Prediction statistics rehearsal requires a valid production-copy timestamp"
        ) from exc
    if copied_at.tzinfo is None or not 0 <= (utc_now() - copied_at).total_seconds() <= 86400:
        _refuse("Prediction statistics production copy must be verified within the last 24 hours")

    tables = database.get("tables")
    required_tables = {
        "official_matches",
        "model_predictions",
        "model_prediction_groups",
        "model_prediction_group_options",
        "model_prediction_runs",
        "model_versions",
    }
    if not isinstance(tables, dict) or not required_tables.issubset(tables):
        _refuse("Prediction statistics rehearsal is missing a required production table copy")

    fully_copied_tables = (
        "official_matches",
        "model_prediction_runs",
        "model_versions",
    )
    for table_name in fully_copied_tables:
        table = tables.get(table_name)
        if (
            not isinstance(table, dict)
            or table.get("copy_mode") != "full"
            or type(table.get("source_rows")) is not int
            or table["source_rows"] <= 0
            or type(table.get("copied_rows")) is not int
            or table.get("copied_rows") != table.get("source_rows")
        ):
            _refuse(f"Prediction statistics rehearsal requires a complete {table_name} copy")

    prediction_table = tables.get("model_predictions")
    sample_match_ids = (
        prediction_table.get("sample_match_ids") if isinstance(prediction_table, dict) else None
    )
    if (
        not isinstance(prediction_table, dict)
        or prediction_table.get("copy_mode") != "indexed_match_sample"
        or type(prediction_table.get("source_rows_estimate")) is not int
        or prediction_table["source_rows_estimate"] <= 0
        or type(prediction_table.get("copied_rows")) is not int
        or prediction_table["copied_rows"] <= 0
        or prediction_table["copied_rows"] >= prediction_table["source_rows_estimate"]
        or prediction_table["copied_rows"] > MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE
        or not isinstance(sample_match_ids, list)
        or not sample_match_ids
        or len(sample_match_ids) > MAX_PRODUCTION_SAMPLE_MATCHES
        or any(type(match_id) is not int or match_id <= 0 for match_id in sample_match_ids)
        or len(sample_match_ids) != len(set(sample_match_ids))
    ):
        _refuse("Prediction statistics rehearsal requires an indexed production prediction sample")

    for table_name in ("model_prediction_groups", "model_prediction_group_options"):
        table = tables.get(table_name)
        table_match_ids = table.get("sample_match_ids") if isinstance(table, dict) else None
        if (
            not isinstance(table, dict)
            or table.get("copy_mode") != "matched_sample"
            or type(table.get("source_rows_estimate")) is not int
            or table["source_rows_estimate"] <= 0
            or type(table.get("copied_rows")) is not int
            or table["copied_rows"] <= 0
            or table["copied_rows"] >= table["source_rows_estimate"]
            or table["copied_rows"] > MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE
            or not isinstance(table_match_ids, list)
            or not table_match_ids
            or any(type(match_id) is not int or match_id <= 0 for match_id in table_match_ids)
            or len(table_match_ids) != len(set(table_match_ids))
            or not set(table_match_ids).issubset(set(sample_match_ids))
        ):
            _refuse(
                f"Prediction statistics rehearsal requires matched production rows from {table_name}"
            )

    queue_seed = report.get("dirty_queue_seed_matches")
    if type(queue_seed) is not int or queue_seed != tables["official_matches"]["copied_rows"]:
        _refuse("Prediction statistics rehearsal queue seed must cover every copied official match")
    for field in (
        "source_trigger_invalidation",
        "application_role_acl",
        "runtime_trigger_write_and_read",
        "down_migration_source_preservation",
        "down_migration_reapplication",
    ):
        if report.get(field) != "passed":
            _refuse(f"Prediction statistics rehearsal is missing {field} proof")

    role = report.get("application_role")
    if (
        not isinstance(role, dict)
        or role.get("name") != "fqp"
        or role.get("superuser") is not False
        or role.get("owns_rollup_tables") is not False
    ):
        _refuse("Prediction statistics rehearsal must verify the restricted non-owner fqp role")

    for field in (
        "migration_up_seconds",
        "migration_down_seconds",
        "migration_lock_wait_ms",
        "batch_refresh_seconds",
    ):
        value = report.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            _refuse(f"Prediction statistics rehearsal requires a non-negative {field} measurement")
    if (
        type(report.get("batch_refresh_rows_read")) is not int
        or report["batch_refresh_rows_read"] <= 0
    ):
        _refuse("Prediction statistics rehearsal requires a measured non-empty refresh batch")
    expected_down = {
        name: REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS[name]
        for name in REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS
    }
    if report.get("down_migration_sha256") != expected_down:
        _refuse(
            "Prediction statistics rehearsal rollback checksum does not match the reviewed down migration"
        )


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
    if pending in (
        REVIEWED_NO_BACKUP_PAIR,
        REVIEWED_NO_BACKUP_ACL,
        REVIEWED_NO_BACKUP_SEASONS,
        REVIEWED_NO_BACKUP_TRADITIONAL_FACTS,
        REVIEWED_NO_BACKUP_ALIASES,
        REVIEWED_NO_BACKUP_RESULT_FACTS,
        REVIEWED_NO_BACKUP_PREDICTION_STATS,
    ):
        _verify_pinned_sql(project_root, pending)
        if pending == REVIEWED_NO_BACKUP_PREDICTION_STATS:
            _verify_pinned_rollback_sql(
                project_root,
                list(REVIEWED_NO_BACKUP_ROLLBACK_CHECKSUMS),
            )
        _verify_no_backup_rehearsal(record, pending, target_sha, evidence_directory)
        return
    _refuse(
        "No-backup release is restricted to pinned migration123, the reviewed124+125 pair, ACL repair126, season identity127, traditional history facts128, fixture identity aliases129, actual result facts130, or production-copy-rehearsed prediction statistics migration131"
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
