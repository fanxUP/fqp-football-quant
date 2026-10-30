"""Regression coverage for the production migration backup policy."""

import hashlib
import json
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


def _write_report(directory: Path, report: dict) -> str:
    path = directory / "no-backup-migration-rehearsal.json"
    path.write_text(json.dumps(report, sort_keys=True) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rehearsal_record(directory: Path) -> dict:
    checksums = {name: policy.REVIEWED_NO_BACKUP_CHECKSUMS[name] for name in MIGRATIONS_124_125}
    report = {
        "status": "passed",
        "target_sha": TARGET_SHA,
        "pending_migrations": MIGRATIONS_124_125,
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
    evidence_sha256 = _write_report(directory, report)
    return {
        "target_sha": TARGET_SHA,
        "migration_copy_dry_run": "passed",
        "migration_transaction_dry_run": "passed",
        "no_backup_authorized": True,
        "no_backup_reason": "Explicit operator preference; both additive migrations were rehearsed in isolation.",
        "no_backup_migration_rehearsal": {
            "status": "passed",
            "pending_migrations": MIGRATIONS_124_125,
            "sha256": checksums,
            "report_path": "no-backup-migration-rehearsal.json",
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
