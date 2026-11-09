"""Regression coverage for the production migration backup policy."""

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ops.server import release_migration_policy as policy

ROOT = Path(__file__).resolve().parents[2]
TARGET_SHA = "5386ecf75e3d0fd2dda0f6537773e3d01731fd17"
MIGRATIONS_124_125 = [
    "124_official_event_season_retention.sql",
    "125_football_fixture_identity.sql",
]
MIGRATION_126 = ["126_official_season_retention_access.sql"]
MIGRATION_128 = ["128_traditional_history_facts.sql"]
MIGRATION_129 = ["129_football_fixture_identity_aliases.sql"]
MIGRATION_130 = ["130_football_fixture_result_facts.sql"]
MIGRATION_131 = ["131_prediction_statistics_rollup.sql"]
MIGRATION_132_133 = [
    "132_prematch_prediction_schedule.sql",
    "133_traditional_market_reference.sql",
]


@pytest.fixture(scope="session")
def migration_131_test_signing_key(tmp_path_factory):
    key_path = tmp_path_factory.mktemp("migration-131-signer") / "id_ed25519"
    subprocess.run(
        [str(policy.TRUSTED_SSH_KEYGEN), "-q", "-t", "ed25519", "-N", "", "-f", str(key_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return key_path


@pytest.fixture
def trusted_migration_131_signer(monkeypatch, migration_131_test_signing_key):
    monkeypatch.setattr(
        policy,
        "TRUSTED_NO_BACKUP_SIGNER_PUBLIC_KEY",
        Path(f"{migration_131_test_signing_key}.pub"),
    )
    return migration_131_test_signing_key


def _write_report(directory: Path, report: dict) -> str:
    name = (
        "prematch-migration-rehearsal.json"
        if report.get("pending_migrations") == MIGRATION_132_133
        else "no-backup-migration-rehearsal.json"
    )
    path = directory / name
    path.write_text(json.dumps(report, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_signed_report(directory: Path, report: dict, signing_key: Path) -> str:
    digest = _write_report(directory, report)
    report_path = directory / "no-backup-migration-rehearsal.json"
    Path(f"{report_path}.sig").unlink(missing_ok=True)
    subprocess.run(
        [
            str(policy.TRUSTED_SSH_KEYGEN),
            "-Y",
            "sign",
            "-f",
            str(signing_key),
            "-n",
            policy.NO_BACKUP_SIGNING_NAMESPACE,
            str(report_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return digest


def rehearsal_record(directory: Path, pending=None) -> dict:
    pending = MIGRATIONS_124_125 if pending is None else pending
    checksums = {name: policy.REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in pending}
    report_name = (
        "prematch-migration-rehearsal.json"
        if pending == MIGRATION_132_133
        else "no-backup-migration-rehearsal.json"
    )
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": pending,
        "migration_sha256": checksums,
        "verified_at": datetime.now(UTC).isoformat(),
        "database": {
            "disposable": True,
            "postgres_major": 16,
            "fixture_kind": "synthetic_schema_fixture",
            "production_data_copy": False,
        },
        "existing_rows_preserved": "passed",
        "constraints_and_triggers_verified": "passed",
        "transaction_rollback_verified": "passed",
        "timeouts": {"lock_seconds": 2, "statement_seconds": 30},
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
    }
    if pending == MIGRATION_126:
        report.update(
            application_role={"name": "fqp", "superuser": False, "owns_retention_table": False},
            application_role_acl="passed",
            application_business_paths="passed",
            acl_rollback_verified="passed",
        )
    if pending == MIGRATION_129:
        report.update(
            application_role={"name": "fqp", "superuser": False, "owns_alias_table": False},
            application_role_acl="passed",
            application_alias_insert_and_read_path="passed",
            application_alias_rollback_verified="passed",
        )
    if pending == MIGRATION_132_133:
        report.update(
            down_migration_sha256=policy.REVIEWED_NO_BACKUP_PREMATCH_ROLLBACK_CHECKSUMS,
            application_role={"name": "fqp", "superuser": False, "owns_new_tables": False},
            application_role_acl="passed",
            application_business_paths="passed",
            published_reference_protection="passed",
            rollback_preserves_runtime_data="passed",
        )
    evidence_sha256 = _write_report(directory, report)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": "Explicit operator preference; both additive migrations were rehearsed in isolation.",
        (
            policy.PREMATCH_REHEARSAL_FIELD
            if pending == MIGRATION_132_133
            else "no_backup_migration_rehearsal"
        ): {
            "status": "passed",
            "pending_migrations": pending,
            "sha256": checksums,
            "report_path": report_name,
            "evidence_sha256": evidence_sha256,
        },
    }


def validate(
    record, pending, *, project_root=ROOT, evidence_directory=None, mode="--apply-no-backup"
):
    policy.validate_release_migrations(
        record,
        mode,
        pending,
        TARGET_SHA,
        project_root=project_root,
        evidence_directory=evidence_directory,
    )


def test_no_backup_allows_only_the_pinned_124_125_pair_with_full_rehearsal(tmp_path):
    validate(
        rehearsal_record(tmp_path),
        MIGRATIONS_124_125,
        evidence_directory=tmp_path,
    )


def test_no_backup_allows_only_the_pinned_129_alias_migration_with_runtime_role_evidence(tmp_path):
    validate(
        rehearsal_record(tmp_path, pending=MIGRATION_129),
        MIGRATION_129,
        evidence_directory=tmp_path,
    )


def test_no_backup_allows_exact_132_133_prematch_pair_with_runtime_and_data_preservation_evidence(
    tmp_path,
):
    validate(
        rehearsal_record(tmp_path, pending=MIGRATION_132_133),
        MIGRATION_132_133,
        evidence_directory=tmp_path,
    )


def test_backup_release_for_132_133_also_requires_prematch_rehearsal(tmp_path, monkeypatch):
    record = rehearsal_record(tmp_path, pending=MIGRATION_132_133)
    backup = tmp_path / "pre-release.dump"
    backup.write_bytes(b"isolated test archive")
    record["backup_path"] = str(backup)
    record["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    validate(record, MIGRATION_132_133, evidence_directory=tmp_path, mode="--apply")


def test_backup_release_for_132_133_rejects_missing_prematch_rehearsal(tmp_path, monkeypatch):
    record = rehearsal_record(tmp_path, pending=MIGRATION_132_133)
    record.pop(policy.PREMATCH_REHEARSAL_FIELD)
    backup = tmp_path / "pre-release.dump"
    backup.write_bytes(b"isolated test archive")
    record["backup_path"] = str(backup)
    record["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    with pytest.raises(SystemExit):
        validate(record, MIGRATION_132_133, evidence_directory=tmp_path, mode="--apply")


@pytest.mark.parametrize(
    "pending",
    [MIGRATION_132_133[:1], MIGRATION_132_133[1:], [*MIGRATION_132_133, "134_unreviewed.sql"]],
)
def test_backup_release_rejects_partial_or_mixed_132_133_sets(pending, tmp_path, monkeypatch):
    record = rehearsal_record(tmp_path, pending=MIGRATION_132_133)
    backup = tmp_path / "pre-release.dump"
    backup.write_bytes(b"isolated test archive")
    record["backup_path"] = str(backup)
    record["backup_sha256"] = hashlib.sha256(backup.read_bytes()).hexdigest()
    monkeypatch.setattr(
        policy.subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 0),
    )
    with pytest.raises(SystemExit, match="exact ordered pair"):
        validate(record, pending, evidence_directory=tmp_path, mode="--apply")


@pytest.mark.parametrize(
    "pending",
    [
        MIGRATION_132_133[:1],
        list(reversed(MIGRATION_132_133)),
        [*MIGRATION_132_133, *MIGRATION_131],
    ],
)
def test_no_backup_rejects_incomplete_or_mixed_prematch_migration_set(pending, tmp_path):
    with pytest.raises(SystemExit):
        validate(
            rehearsal_record(tmp_path, pending=MIGRATION_132_133),
            pending,
            evidence_directory=tmp_path,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role", {"name": "postgres", "superuser": True, "owns_new_tables": True}),
        ("application_role_acl", "failed"),
        ("application_business_paths", "not_run"),
        ("published_reference_protection", "failed"),
        ("rollback_preserves_runtime_data", "not_run"),
        ("down_migration_sha256", {}),
    ],
)
def test_no_backup_prematch_requires_restricted_role_and_non_destructive_rollback(
    field, value, tmp_path
):
    record = rehearsal_record(tmp_path, pending=MIGRATION_132_133)
    report_path = tmp_path / record[policy.PREMATCH_REHEARSAL_FIELD]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record[policy.PREMATCH_REHEARSAL_FIELD]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit):
        validate(record, MIGRATION_132_133, evidence_directory=tmp_path)


def test_release_policy_cli_verifies_sibling_report_hash(tmp_path):
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text(json.dumps(rehearsal_record(tmp_path)))
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops/server/release_migration_policy.py"),
            str(evidence_path),
            "apply-no-backup",
            json.dumps(MIGRATIONS_124_125),
            TARGET_SHA,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Migration release policy passed" in result.stdout


@pytest.mark.parametrize(
    "pending",
    [
        [MIGRATIONS_124_125[0]],
        [MIGRATIONS_124_125[1]],
        list(reversed(MIGRATIONS_124_125)),
        [*MIGRATIONS_124_125, "126_unreviewed.sql"],
        ["126_unreviewed.sql"],
        [*MIGRATION_129, *MIGRATION_128],
    ],
)
def test_no_backup_rejects_any_migration_set_other_than_exact_reviewed_pair(pending, tmp_path):
    with pytest.raises(SystemExit, match="restricted|reviewed|allowlist"):
        validate(rehearsal_record(tmp_path), pending, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("no_backup_authorized", False),
        ("migration_copy_dry_run", "not_run"),
        ("migration_transaction_dry_run", "not_run"),
    ],
)
def test_no_backup_rejects_missing_operator_or_migration_rehearsal_evidence(field, value, tmp_path):
    record = rehearsal_record(tmp_path)
    record[field] = value
    with pytest.raises(SystemExit):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "failed"),
        (
            "database",
            {
                "disposable": True,
                "postgres_major": 16,
                "fixture_kind": "production_database_copy",
                "production_data_copy": True,
            },
        ),
        ("existing_rows_preserved", "failed"),
        ("constraints_and_triggers_verified", "failed"),
        ("transaction_rollback_verified", "failed"),
        ("pending_migrations", [MIGRATIONS_124_125[0]]),
        ("migration_sha256", {MIGRATIONS_124_125[0]: "0" * 64}),
        ("timeouts", {"lock_seconds": 5, "statement_seconds": 30}),
        ("test_results", {"passed": 1, "failed": 0, "skipped": 1}),
    ],
)
def test_no_backup_requires_matching_isolated_rehearsal_report(field, value, tmp_path):
    record = rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


def test_no_backup_rehearsal_must_match_release_target_sha(tmp_path):
    record = rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["target_sha"] = "0" * 40
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="target SHA"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)

    record = rehearsal_record(tmp_path)
    record["target_sha"] = "0" * 40
    with pytest.raises(SystemExit, match="target SHA"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


def test_rehearsal_report_path_cannot_escape_release_evidence_directory(tmp_path):
    record = rehearsal_record(tmp_path)
    record["no_backup_migration_rehearsal"]["report_path"] = "../outside.json"
    with pytest.raises(SystemExit, match="sibling file"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


def test_no_backup_rehearsal_report_must_be_recent_and_timezone_aware(tmp_path):
    record = rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["verified_at"] = "2026-10-01T12:00:00+00:00"
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="last 24 hours"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)

    report["verified_at"] = "2026-10-30T12:00:00"
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="last 24 hours"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


def test_sql_checksum_pins_are_checked_against_the_checked_out_files(tmp_path):
    migration_dir = tmp_path / "sql"
    migration_dir.mkdir()
    for name in MIGRATIONS_124_125:
        source = (ROOT / "sql" / name).read_bytes()
        (migration_dir / name).write_bytes(source)
    (migration_dir / MIGRATIONS_124_125[0]).write_bytes(b"changed after review")

    with pytest.raises(SystemExit, match="checkout|checksum"):
        validate(
            rehearsal_record(tmp_path),
            MIGRATIONS_124_125,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )


def test_rehearsal_report_hash_is_verified(tmp_path):
    record = rehearsal_record(tmp_path)
    (tmp_path / record["no_backup_migration_rehearsal"]["report_path"]).write_text("tampered\n")
    with pytest.raises(SystemExit, match="SHA-256"):
        validate(record, MIGRATIONS_124_125, evidence_directory=tmp_path)


def test_migration_123_no_backup_exception_remains_checksum_pinned():
    name = "123_football_history_odds_invalid_timezone.sql"
    record = {
        "no_backup_authorized": True,
        "no_backup_reason": "Existing reviewed no-backup exception.",
        "migration_transaction_dry_run": "passed",
    }
    validate(record, [name])


def test_other_pending_migrations_still_require_a_recent_verified_backup(tmp_path, monkeypatch):
    name = "012_test.sql"
    sql_dir = tmp_path / "sql"
    sql_dir.mkdir()
    (sql_dir / name).write_text("SELECT 1;\n")
    backup = tmp_path / "database.dump"
    backup.write_bytes(b"test archive")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    called = []
    monkeypatch.setattr(policy.subprocess, "run", lambda *args, **kwargs: called.append(args))
    monkeypatch.setattr(policy, "utc_now", lambda: datetime.now(UTC))

    with pytest.raises(SystemExit, match="verified pre-deployment backup"):
        validate(
            {"migration_copy_dry_run": "passed"}, [name], project_root=tmp_path, mode="--apply"
        )

    record = {
        "migration_copy_dry_run": "passed",
        "backup_path": str(backup),
        "backup_sha256": digest,
    }
    validate(record, [name], project_root=tmp_path, mode="--apply")
    assert called and called[0][0] == ["pg_restore", "--list", str(backup)]


def test_no_pending_migrations_need_no_backup_evidence():
    validate({}, [])


def traditional_facts_rehearsal_record(directory: Path) -> dict:
    pending = MIGRATION_128
    checksum = hashlib.sha256((ROOT / "sql" / pending[0]).read_bytes()).hexdigest()
    checksums = {pending[0]: checksum}
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": pending,
        "migration_sha256": checksums,
        "verified_at": datetime.now(UTC).isoformat(),
        "database": {
            "disposable": True,
            "postgres_major": 16,
            "fixture_kind": "synthetic_schema_fixture",
            "production_data_copy": False,
        },
        "existing_rows_preserved": "passed",
        "constraints_and_triggers_verified": "passed",
        "transaction_rollback_verified": "passed",
        "timeouts": {"lock_seconds": 2, "statement_seconds": 30},
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "application_role": {"name": "fqp", "superuser": False},
        "application_role_catalog_access": "passed",
        "application_catalog_read_path": "passed",
        "application_import_write_path": "passed",
    }
    evidence_sha256 = _write_report(directory, report)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": "Explicit operator preference; migration 128 was rehearsed in isolation.",
        "no_backup_migration_rehearsal": {
            "status": "passed",
            "pending_migrations": pending,
            "sha256": checksums,
            "report_path": "no-backup-migration-rehearsal.json",
            "evidence_sha256": evidence_sha256,
        },
    }


def test_no_backup_allows_only_pinned_128_with_application_role_rehearsal(tmp_path):
    validate(
        traditional_facts_rehearsal_record(tmp_path),
        MIGRATION_128,
        evidence_directory=tmp_path,
    )


@pytest.mark.parametrize(
    "pending",
    [
        ["128_traditional_history_facts.sql", "127_football_fixture_seasons.sql"],
        ["128_unreviewed.sql"],
    ],
)
def test_no_backup_128_rejects_other_migration_sets(pending, tmp_path):
    record = traditional_facts_rehearsal_record(tmp_path)
    record["no_backup_migration_rehearsal"]["pending_migrations"] = pending
    with pytest.raises(SystemExit, match="restricted|reviewed|allowlist"):
        validate(record, pending, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role_catalog_access", "failed"),
        ("application_catalog_read_path", "not_run"),
        ("application_import_write_path", "not_run"),
        ("application_role", {"name": "postgres", "superuser": True}),
    ],
)
def test_no_backup_128_requires_runtime_role_catalog_and_import_paths(field, value, tmp_path):
    record = traditional_facts_rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="application|runtime"):
        validate(record, MIGRATION_128, evidence_directory=tmp_path)


def test_no_backup_allows_pinned_acl_repair_with_runtime_role_evidence(tmp_path):
    validate(rehearsal_record(tmp_path, MIGRATION_126), MIGRATION_126, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role_acl", "not_run"),
        ("application_business_paths", "not_run"),
        ("acl_rollback_verified", "not_run"),
        ("application_role", {"name": "postgres", "superuser": True, "owns_retention_table": True}),
        ("application_role", {"name": "fqp", "superuser": False, "owns_retention_table": True}),
        ("application_role", {"name": "fqp", "superuser": True, "owns_retention_table": False}),
        ("application_role", None),
    ],
)
def test_acl_repair_requires_restricted_runtime_role_and_rollback_proof(field, value, tmp_path):
    record = rehearsal_record(tmp_path, MIGRATION_126)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="runtime|ACL|application"):
        validate(record, MIGRATION_126, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "pending",
    [
        [*MIGRATIONS_124_125, *MIGRATION_126],
        [*MIGRATION_126, "127_unreviewed.sql"],
    ],
)
def test_acl_repair_cannot_expand_no_backup_migration_set(tmp_path, pending):
    with pytest.raises(SystemExit, match="restricted|reviewed"):
        validate(rehearsal_record(tmp_path, MIGRATION_126), pending, evidence_directory=tmp_path)


def test_acl_repair_sql_change_is_rejected(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / MIGRATION_126[0]).write_text(
        "GRANT ALL ON ALL TABLES IN SCHEMA public TO fqp;"
    )
    with pytest.raises(SystemExit, match="checksum"):
        validate(
            rehearsal_record(tmp_path, MIGRATION_126),
            MIGRATION_126,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )


MIGRATION_127 = ["127_football_fixture_seasons.sql"]


def season_rehearsal_record(directory):
    # The helper needs a report before the new checksum is implemented (RED).
    pending = MIGRATION_127
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": pending,
        "migration_sha256": {
            pending[0]: "7c0c61920f62680e3f4951e5dd98dd57a9588f12315df1e64c570f69d725023c"
        },
        "verified_at": datetime.now(UTC).isoformat(),
        "database": {
            "disposable": True,
            "postgres_major": 16,
            "fixture_kind": "synthetic_schema_fixture",
            "production_data_copy": False,
        },
        "existing_rows_preserved": "passed",
        "constraints_and_triggers_verified": "passed",
        "transaction_rollback_verified": "passed",
        "timeouts": {"lock_seconds": 2, "statement_seconds": 30},
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "application_role": {
            "name": "fqp",
            "superuser": False,
            "owns_season_identity_tables": False,
        },
        "application_role_acl": "passed",
        "application_business_paths": "passed",
        "acl_rollback_verified": "passed",
    }
    digest = _write_report(directory, report)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": "Explicit no-backup instruction; additive127 independently rehearsed.",
        "no_backup_migration_rehearsal": {
            "status": "passed",
            "pending_migrations": pending,
            "sha256": report["migration_sha256"],
            "report_path": "no-backup-migration-rehearsal.json",
            "evidence_sha256": digest,
        },
    }


def test_season_127_allows_only_pinned_sql_and_full_runtime_rehearsal(tmp_path):
    validate(season_rehearsal_record(tmp_path), MIGRATION_127, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role_acl", "not_run"),
        ("application_business_paths", "not_run"),
        ("acl_rollback_verified", "not_run"),
        (
            "application_role",
            {"name": "postgres", "superuser": True, "owns_season_identity_tables": True},
        ),
        (
            "application_role",
            {"name": "fqp", "superuser": False, "owns_season_identity_tables": True},
        ),
        ("application_role", None),
    ],
)
def test_season_127_rejects_missing_runtime_role_or_acl_proof(tmp_path, field, value):
    record = season_rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="runtime|ACL|application"):
        validate(record, MIGRATION_127, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "pending",
    [
        MIGRATION_127 + MIGRATION_126,
        MIGRATION_126 + MIGRATION_127,
        MIGRATION_127 + ["128_unknown.sql"],
    ],
)
def test_season_127_never_allows_extra_migrations(tmp_path, pending):
    with pytest.raises(SystemExit, match="restricted|reviewed"):
        validate(season_rehearsal_record(tmp_path), pending, evidence_directory=tmp_path)


def test_season_127_sql_tampering_refused(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / MIGRATION_127[0]).write_text(
        "GRANT ALL ON ALL TABLES IN SCHEMA public TO fqp;"
    )
    with pytest.raises(SystemExit, match="checksum"):
        validate(
            season_rehearsal_record(tmp_path),
            MIGRATION_127,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )


def result_fact_rehearsal_record(directory: Path) -> dict:
    pending = MIGRATION_130
    checksums = {name: policy.REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in pending}
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": pending,
        "migration_sha256": checksums,
        "verified_at": datetime.now(UTC).isoformat(),
        "database": {
            "disposable": True,
            "postgres_major": 16,
            "fixture_kind": "synthetic_schema_fixture",
            "production_data_copy": False,
        },
        "existing_rows_preserved": "passed",
        "constraints_and_triggers_verified": "passed",
        "transaction_rollback_verified": "passed",
        "timeouts": {"lock_seconds": 2, "statement_seconds": 30},
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "application_role": {
            "name": "fqp",
            "superuser": False,
            "owns_result_fact_table": False,
        },
        "application_role_acl": "passed",
        "result_fact_insert_and_model_read": "passed",
        "source_fixture_mismatch_rejected": "passed",
        "append_only_enforced": "passed",
        "result_fact_rollback_verified": "passed",
    }
    digest = _write_report(directory, report)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": "Explicit operator preference; migration 130 was rehearsed in isolation.",
        "no_backup_migration_rehearsal": {
            "status": "passed",
            "pending_migrations": pending,
            "sha256": checksums,
            "report_path": "no-backup-migration-rehearsal.json",
            "evidence_sha256": digest,
        },
    }


def prediction_statistics_rehearsal_record(directory: Path, signing_key: Path) -> dict:
    checksums = {
        MIGRATION_131[0]: ("a98300da5bfa7ec8b1e1c21cabec83ec580a4346cb6e6835707d831706c55b1f")
    }
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": MIGRATION_131,
        "migration_sha256": checksums,
        "down_migration_sha256": {
            "131_prediction_statistics_rollup.down.sql": (
                "2b99a556dccf22e7ae181cd9a8bb9232385338483f3bf91180839e6a0329e4c3"
            )
        },
        "verified_at": datetime.now(UTC).isoformat(),
        "database": {
            "disposable": True,
            "postgres_major": 16,
            "fixture_kind": "targeted_production_schema_data_copy",
            "production_data_copy": True,
            "production_copy_at": datetime.now(UTC).isoformat(),
            "schema_sha256": "a" * 64,
            "source_revision": "4a7a37aa57b885cc3ae332731b6a6e273dd49bff",
            "tables": {
                "official_matches": {
                    "source_rows": 4050,
                    "copied_rows": 4050,
                    "copy_mode": "full",
                },
                "model_predictions": {
                    "source_rows_estimate": 15577300,
                    "copied_rows": 100,
                    "copy_mode": "indexed_match_sample",
                    "sample_match_ids": [101, 102],
                },
                "model_prediction_groups": {
                    "source_rows_estimate": 186979,
                    "copied_rows": 20,
                    "copy_mode": "matched_sample",
                    "sample_match_ids": [101, 102],
                },
                "model_prediction_group_options": {
                    "source_rows_estimate": 1225921,
                    "copied_rows": 40,
                    "copy_mode": "matched_sample",
                    "sample_match_ids": [101, 102],
                },
                "model_prediction_runs": {
                    "source_rows": 485,
                    "copied_rows": 485,
                    "copy_mode": "full",
                },
                "model_versions": {
                    "source_rows": 66,
                    "copied_rows": 66,
                    "copy_mode": "full",
                },
            },
        },
        "existing_rows_preserved": "passed",
        "constraints_and_triggers_verified": "passed",
        "transaction_rollback_verified": "passed",
        "source_trigger_invalidation": "passed",
        "dirty_queue_seed_matches": 4050,
        "migration_up_seconds": 3.2,
        "migration_down_seconds": 0.4,
        "migration_lock_wait_ms": 4,
        "batch_refresh_seconds": 1.2,
        "batch_refresh_rows_read": 870,
        "timeouts": {"lock_seconds": 2, "statement_seconds": 30},
        "test_results": {"passed": 1, "failed": 0, "skipped": 0},
        "application_role": {
            "name": "fqp",
            "superuser": False,
            "owns_rollup_tables": False,
        },
        "application_role_acl": "passed",
        "runtime_trigger_write_and_read": "passed",
        "down_migration_source_preservation": "passed",
        "down_migration_reapplication": "passed",
    }
    digest = _write_signed_report(directory, report, signing_key)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": (
            "Explicit operator preference; migration 131 is limited to rebuildable "
            "derived statistics and is rehearsed against a targeted current production copy."
        ),
        "no_backup_migration_rehearsal": {
            "status": "passed",
            "pending_migrations": MIGRATION_131,
            "sha256": checksums,
            "report_path": "no-backup-migration-rehearsal.json",
            "evidence_sha256": digest,
        },
    }


def _update_signed_rehearsal(tmp_path: Path, record: dict, report: dict, signing_key: Path) -> dict:
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_signed_report(
        tmp_path, report, signing_key
    )
    return record


def test_no_backup_allows_only_pinned_131_with_targeted_production_copy(
    tmp_path, trusted_migration_131_signer
):
    validate(
        prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer),
        MIGRATION_131,
        evidence_directory=tmp_path,
    )


def test_no_backup_131_signature_verification_ignores_path_ssh_keygen(
    tmp_path, monkeypatch, trusted_migration_131_signer
):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    marker = tmp_path / "path-ssh-keygen-was-used"
    fake_ssh_keygen = tmp_path / "ssh-keygen"
    fake_ssh_keygen.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n")
    fake_ssh_keygen.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")

    validate(record, MIGRATION_131, evidence_directory=tmp_path)

    assert not marker.exists()


def test_no_backup_131_rejects_unsigned_rehearsal_report(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    Path(f"{tmp_path / 'no-backup-migration-rehearsal.json'}.sig").unlink()
    with pytest.raises(SystemExit, match="signed report"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_rejects_tampered_rehearsal_signature(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    Path(f"{tmp_path / 'no-backup-migration-rehearsal.json'}.sig").write_text("invalid")
    with pytest.raises(SystemExit, match="signature is invalid"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_rejects_mixed_migration_sets(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="restricted|reviewed"):
        validate(record, [*MIGRATION_130, *MIGRATION_131], evidence_directory=tmp_path)


def test_no_backup_131_rejects_synthetic_only_rehearsal(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["database"]["fixture_kind"] = "synthetic_schema_fixture"
    report["database"]["production_data_copy"] = False
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="fixture and production-copy scope"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_requires_every_migration_source_table(
    tmp_path, trusted_migration_131_signer
):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    del report["database"]["tables"]["model_prediction_group_options"]
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="missing a required production table copy"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_bounds_indexed_production_sample_size(
    tmp_path, trusted_migration_131_signer
):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["database"]["tables"]["model_predictions"]["copied_rows"] = (
        policy.MAX_PRODUCTION_SAMPLE_ROWS_PER_TABLE + 1
    )
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="indexed production prediction sample"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_bounds_number_of_sample_matches(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    match_ids = list(range(1, policy.MAX_PRODUCTION_SAMPLE_MATCHES + 2))
    report["database"]["tables"]["model_predictions"]["sample_match_ids"] = match_ids
    report["database"]["tables"]["model_prediction_groups"]["sample_match_ids"] = match_ids
    report["database"]["tables"]["model_prediction_group_options"]["sample_match_ids"] = match_ids
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="indexed production prediction sample"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_requires_exact_official_match_copy_and_seed_count(
    tmp_path, trusted_migration_131_signer
):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["database"]["tables"]["official_matches"]["copied_rows"] -= 1
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="complete official_matches copy"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_requires_a_recent_production_copy(tmp_path, trusted_migration_131_signer):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report["database"]["production_copy_at"] = "2020-01-01T00:00:00+00:00"
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit, match="last 24 hours"):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role_acl", "not_run"),
        ("source_trigger_invalidation", "not_run"),
        ("runtime_trigger_write_and_read", "not_run"),
        ("down_migration_source_preservation", "not_run"),
        ("down_migration_reapplication", "not_run"),
        ("migration_up_seconds", -1),
        ("migration_lock_wait_ms", True),
        ("batch_refresh_rows_read", 0),
        ("dirty_queue_seed_matches", 4049),
        (
            "down_migration_sha256",
            {"131_prediction_statistics_rollup.down.sql": "0" * 64},
        ),
        (
            "application_role",
            {"name": "fqp", "superuser": True, "owns_rollup_tables": False},
        ),
        (
            "application_role",
            {"name": "fqp", "superuser": False, "owns_rollup_tables": True},
        ),
    ],
)
def test_no_backup_131_requires_runtime_and_rollback_proof(
    tmp_path, field, value, trusted_migration_131_signer
):
    record = prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record = _update_signed_rehearsal(tmp_path, record, report, trusted_migration_131_signer)
    with pytest.raises(SystemExit):
        validate(record, MIGRATION_131, evidence_directory=tmp_path)


def test_no_backup_131_rejects_up_migration_tampering(tmp_path, trusted_migration_131_signer):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / MIGRATION_131[0]).write_text("DROP TABLE model_predictions;")
    with pytest.raises(SystemExit, match="checksum"):
        validate(
            prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer),
            MIGRATION_131,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )


def test_no_backup_131_rejects_down_migration_tampering(tmp_path, trusted_migration_131_signer):
    down_dir = tmp_path / "sql" / "down"
    down_dir.mkdir(parents=True)
    (tmp_path / "sql" / MIGRATION_131[0]).write_bytes(
        (ROOT / "sql" / MIGRATION_131[0]).read_bytes()
    )
    (down_dir / "131_prediction_statistics_rollup.down.sql").write_text(
        "DROP TABLE official_matches;"
    )
    with pytest.raises(SystemExit, match="checksum"):
        validate(
            prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer),
            MIGRATION_131,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )


def test_no_backup_131_policy_file_accepts_signed_production_rehearsal(
    tmp_path, trusted_migration_131_signer
):
    evidence_path = tmp_path / "release-evidence.json"
    evidence_path.write_text(
        json.dumps(prediction_statistics_rehearsal_record(tmp_path, trusted_migration_131_signer))
    )
    policy.validate_release_file(
        evidence_path,
        "--apply-no-backup",
        MIGRATION_131,
        TARGET_SHA,
        project_root=ROOT,
    )


def test_no_backup_allows_only_pinned_130_with_result_fact_runtime_rehearsal(tmp_path):
    validate(
        result_fact_rehearsal_record(tmp_path),
        MIGRATION_130,
        evidence_directory=tmp_path,
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("application_role_acl", "not_run"),
        ("result_fact_insert_and_model_read", "not_run"),
        ("source_fixture_mismatch_rejected", "not_run"),
        ("append_only_enforced", "not_run"),
        ("result_fact_rollback_verified", "not_run"),
        ("application_role", {"name": "postgres", "superuser": True}),
        (
            "application_role",
            {"name": "fqp", "superuser": False, "owns_result_fact_table": True},
        ),
    ],
)
def test_no_backup_130_requires_runtime_role_and_data_contract_proof(tmp_path, field, value):
    record = result_fact_rehearsal_record(tmp_path)
    report_path = tmp_path / record["no_backup_migration_rehearsal"]["report_path"]
    report = json.loads(report_path.read_text())
    report[field] = value
    record["no_backup_migration_rehearsal"]["evidence_sha256"] = _write_report(tmp_path, report)
    with pytest.raises(SystemExit, match="runtime|ACL|source binding|append-only|rollback"):
        validate(record, MIGRATION_130, evidence_directory=tmp_path)


def test_no_backup_130_rejects_other_migration_sets(tmp_path):
    record = result_fact_rehearsal_record(tmp_path)
    with pytest.raises(SystemExit, match="restricted|reviewed"):
        validate(record, MIGRATION_129 + MIGRATION_130, evidence_directory=tmp_path)


def test_no_backup_130_sql_tampering_is_rejected(tmp_path):
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql" / MIGRATION_130[0]).write_text("DROP TABLE official_results;")
    with pytest.raises(SystemExit, match="checksum"):
        validate(
            result_fact_rehearsal_record(tmp_path),
            MIGRATION_130,
            project_root=tmp_path,
            evidence_directory=tmp_path,
        )
