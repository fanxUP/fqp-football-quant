"""Manual full PostgreSQL backup. Never registered in the automatic scheduler.

Uses custom pg_dump archives and SHA256. Archive validation is distinct from
an actual restore, which needs an explicit empty fqp_restore_* database URL.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import parse_dsn

from apps.backend.src.db import get_db
from scripts.business_time import utc_now_iso
from scripts.ops_storage import store_backup_log


def _now(value: datetime | None = None) -> str:
    return utc_now_iso(value)


def _get_backup_dir() -> str:
    return os.environ.get("BACKUP_DIR", "./backups")


def _ensure_backup_dir(backup_dir: str) -> None:
    Path(backup_dir).mkdir(parents=True, exist_ok=True)


def _checksum(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _pg_environment(dsn: str) -> tuple[str, dict[str, str]]:
    params = parse_dsn(dsn)
    env_keys = {
        "host": "PGHOST",
        "hostaddr": "PGHOSTADDR",
        "port": "PGPORT",
        "user": "PGUSER",
        "password": "PGPASSWORD",
        "sslmode": "PGSSLMODE",
        "sslrootcert": "PGSSLROOTCERT",
        "sslcert": "PGSSLCERT",
        "sslkey": "PGSSLKEY",
        "connect_timeout": "PGCONNECT_TIMEOUT",
        "application_name": "PGAPPNAME",
        "options": "PGOPTIONS",
    }
    if not params.get("dbname") or set(params) - set(env_keys) - {"dbname"}:
        raise RuntimeError("Explicit database name and supported connection options are required")
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
    environment.update({env_keys[key]: value for key, value in params.items() if key in env_keys})
    return params["dbname"], environment


def _create_backup(backup_dir: str) -> tuple[str | None, int, str | None]:
    tool = shutil.which("pg_dump")
    db_url = os.environ.get("DATABASE_URL")
    if not tool or not db_url:
        return None, 0, "pg_dump and explicit DATABASE_URL are required; no partial-export fallback"
    _ensure_backup_dir(backup_dir)
    path = Path(backup_dir) / f"fqp_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.dump"
    temporary = path.with_suffix(".partial")
    try:
        # Keep credentials out of process arguments and never print the environment.
        database_name, dump_env = _pg_environment(db_url)
        with temporary.open("xb") as output:
            temporary.chmod(0o600)
            subprocess.run(
                [tool, "--format=custom", "--dbname", database_name],
                env=dump_env,
                stdout=output,
                stderr=subprocess.PIPE,
                check=True,
                timeout=3600,
            )
        if not temporary.stat().st_size:
            raise RuntimeError("Empty PostgreSQL archive")
        temporary.rename(path)
        sidecar = path.with_suffix(".dump.sha256")
        sidecar.write_text(f"{_checksum(path)}  {path.name}\n")
        sidecar.chmod(0o600)
        return str(path), path.stat().st_size, None
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        # Do not include driver/tool stderr, which can contain credentials.
        return None, 0, f"Full backup failed ({type(exc).__name__}); inspect private pg_dump logs"


def _find_latest_backup(backup_dir: str) -> str | None:
    files = list(Path(backup_dir).glob("fqp_*.dump"))
    return str(max(files, key=lambda path: path.stat().st_mtime)) if files else None


def _verify_backup_integrity(filepath: str) -> dict[str, Any]:
    path = Path(filepath)
    result: dict[str, Any] = {
        "exists": path.is_file(),
        "size_bytes": 0,
        "size_ok": False,
        "integrity_ok": False,
        "sha256": None,
        "error": None,
    }
    if not path.is_file():
        result["error"] = "Backup file is missing"
        return result
    result.update(size_bytes=path.stat().st_size, size_ok=path.stat().st_size > 0)
    tool = shutil.which("pg_restore")
    sidecar = path.with_suffix(path.suffix + ".sha256")
    if not tool or not sidecar.is_file() or path.suffix != ".dump":
        result["error"] = "Custom archive, pg_restore and SHA256 sidecar are required"
        return result
    try:
        actual = _checksum(path)
        if actual != sidecar.read_text().split()[0]:
            raise RuntimeError("Backup SHA256 mismatch")
        listing = subprocess.run(
            [tool, "--list", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        required = ("official_matches", "ticket_settlements", "bankroll_transactions")
        if not all(f"TABLE DATA public {name} " in listing for name in required):
            raise RuntimeError("Essential tables are missing from archive directory")
        result.update(integrity_ok=True, sha256=actual)
    except Exception as exc:
        result["error"] = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else f"Archive validation failed ({type(exc).__name__})"
        )
    return result


def _test_restore(filepath: str) -> bool | None:
    """Restore only into an explicitly configured, empty isolated database."""
    target = os.environ.get("FQP_RESTORE_TEST_DATABASE_URL")
    if not target:
        return None
    tool = shutil.which("pg_restore")
    if not tool:
        return False
    try:
        params = parse_dsn(target)
        if not params.get("dbname", "").startswith("fqp_restore_"):
            return False
        with psycopg2.connect(target, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT current_database(), (SELECT COUNT(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog', 'information_schema')), current_setting('server_encoding')"
                )
                name, tables, encoding = cur.fetchone()
                if not name.startswith("fqp_restore_") or tables or encoding != "UTF8":
                    return False
        # Connection options go through the environment, never secret argv.
        database_name, restore_env = _pg_environment(target)
        subprocess.run(
            [
                tool,
                "--dbname",
                database_name,
                "--exit-on-error",
                "--single-transaction",
                "--no-owner",
                "--no-privileges",
                filepath,
            ],
            env=restore_env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=3600,
        )
        with psycopg2.connect(target, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                for table in ("official_matches", "ticket_settlements", "bankroll_transactions"):
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    cur.fetchone()
        return True
    except Exception:
        return False


def run(dry_run: bool = False) -> dict[str, Any]:
    if dry_run:
        return {
            "status": "dry_run",
            "backup_dir": _get_backup_dir(),
            "message": "Manual custom pg_dump backup; no writes performed",
        }
    started_at = _now()
    filepath, size, error = _create_backup(_get_backup_dir())
    verification = (
        _verify_backup_integrity(filepath)
        if filepath
        else {"integrity_ok": False, "sha256": None, "error": error}
    )
    restore_ok = _test_restore(filepath) if filepath and verification["integrity_ok"] else None
    success = bool(verification["integrity_ok"] and restore_ok is not False)
    with get_db() as conn:
        store_backup_log(
            conn,
            {
                "backup_type": "full",
                "backup_path": filepath,
                "backup_size_bytes": size,
                "started_at": started_at,
                "finished_at": _now(),
                "success": success,
                "integrity_check_passed": verification["integrity_ok"],
                "restore_test_passed": restore_ok,
                "error_message": verification.get("error")
                or ("Isolated restore failed" if restore_ok is False else None),
                "backup_command": "pg_dump --format=custom (manual)",
            },
        )
    # Retention/deletion is an explicit separate operation; preserve older backups.
    return {
        "status": "ok" if success else "failed",
        "backup_file": filepath,
        "size_bytes": size,
        "sha256": verification["sha256"],
        "integrity_check": verification["integrity_ok"],
        "restore_test": restore_ok,
        "success": success,
        "error": verification.get("error"),
        "note": (
            "Archive verification failed"
            if not verification["integrity_ok"]
            else "Archive/hash validated; actual restore was not run"
            if restore_ok is None
            else "Isolated restore passed"
            if restore_ok
            else "Isolated restore failed"
        ),
    }


if __name__ == "__main__":
    import sys

    print(run(dry_run="--dry-run" in sys.argv))
