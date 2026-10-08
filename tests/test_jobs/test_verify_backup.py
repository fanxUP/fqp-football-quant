import hashlib
from unittest.mock import Mock

from scripts.jobs import verify_backup as backup


def test_restore_without_explicit_target_is_not_claimed(monkeypatch, tmp_path):
    monkeypatch.delenv("FQP_RESTORE_TEST_DATABASE_URL", raising=False)
    restore = Mock()
    monkeypatch.setattr(backup.subprocess, "run", restore)
    assert backup._test_restore(str(tmp_path / "backup.dump")) is None
    restore.assert_not_called()


def test_restore_refuses_production_database(monkeypatch, tmp_path):
    monkeypatch.setenv("FQP_RESTORE_TEST_DATABASE_URL", "dbname=fqp")
    monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_restore")
    connect = Mock()
    monkeypatch.setattr(backup.psycopg2, "connect", connect)
    assert backup._test_restore(str(tmp_path / "backup.dump")) is False
    connect.assert_not_called()


def test_archive_checksum_mismatch_refuses_restore(monkeypatch, tmp_path):
    path = tmp_path / "backup.dump"
    path.write_bytes(b"archive")
    path.with_suffix(".dump.sha256").write_text("0" * 64)
    monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_restore")
    restore = Mock()
    monkeypatch.setattr(backup.subprocess, "run", restore)
    result = backup._verify_backup_integrity(str(path))
    assert result["integrity_ok"] is False
    assert result["error"] == "Backup SHA256 mismatch"
    restore.assert_not_called()


def test_archive_validation_requires_all_critical_tables(monkeypatch, tmp_path):
    path = tmp_path / "backup.dump"
    path.write_bytes(b"archive")
    path.with_suffix(".dump.sha256").write_text(hashlib.sha256(b"archive").hexdigest())
    monkeypatch.setattr(backup.shutil, "which", lambda _: "/usr/bin/pg_restore")
    run = Mock(return_value=Mock(stdout="TABLE DATA public official_matches fqp\n"))
    monkeypatch.setattr(backup.subprocess, "run", run)
    assert backup._verify_backup_integrity(str(path))["integrity_ok"] is False
    run.return_value.stdout = "".join(
        f"TABLE DATA public {name} fqp\n"
        for name in ("official_matches", "ticket_settlements", "bankroll_transactions")
    )
    assert backup._verify_backup_integrity(str(path))["integrity_ok"] is True
