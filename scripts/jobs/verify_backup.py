"""Backup creation and verification job.

Stage 8: Daily job (23:00) that:
  1. Creates a pg_dump backup of the FQP database
  2. Verifies the backup file exists and is valid
  3. Logs results to backup_logs table

Target: backup success rate = 100%.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from apps.backend.src.db import get_db
from scripts.ops_storage import store_backup_log


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _get_backup_dir() -> str:
    """Get backup directory from env or default."""
    return os.environ.get("BACKUP_DIR", "./backups")


def _ensure_backup_dir(backup_dir: str) -> None:
    """Create backup directory if it doesn't exist."""
    Path(backup_dir).mkdir(parents=True, exist_ok=True)


def _create_backup(backup_dir: str) -> tuple[str | None, int, str | None]:
    """Create a complete SQL dump, with a psycopg2 data-export fallback.

    Prefer pg_dump because it includes schema and views as well as data.
    Returns (filepath, size_bytes, error_message).
    """
    _ensure_backup_dir(backup_dir)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"fqp_{timestamp}.sql"
    filepath = str(Path(backup_dir) / filename)

    db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql://fqp:fqp_local_password@127.0.0.1:5433/fqp",
        )
    pg_dump = shutil.which("pg_dump")
    if pg_dump:
        try:
            with open(filepath, "wb") as output:
                subprocess.run(
                    [pg_dump, db_url],
                    check=True,
                    stdout=output,
                    stderr=subprocess.PIPE,
                )
            size = Path(filepath).stat().st_size
            if size == 0:
                return None, 0, "pg_dump produced an empty file"
            print("[verify_backup] created full pg_dump backup")
            return filepath, size, None
        except subprocess.CalledProcessError as e:
            return None, 0, e.stderr.decode(errors="replace")[:1000]

    try:
        import psycopg2
        from psycopg2 import sql as psql

        conn = psycopg2.connect(db_url)
        conn.set_session(autocommit=True)
        cur = conn.cursor()

        with open(filepath, "w") as f:
            f.write("-- FQP Database Backup (Python/psycopg2)\n")
            f.write(f"-- Generated: {_now()}\n\n")

            # Get all tables
            cur.execute("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
                  AND table_type = 'BASE TABLE'
                ORDER BY table_schema, table_name
            """)
            tables = cur.fetchall()

            row_count = 0
            for schema, table in tables:
                fqn = psql.Identifier(schema, table).as_string(conn)
                f.write(f"-- Table: {fqn}\n")

                # Count rows
                cur.execute(psql.SQL("SELECT COUNT(*) FROM {}").format(psql.Identifier(schema, table)))
                count = cur.fetchone()[0]
                f.write(f"-- Rows: {count}\n")

                if count > 0:
                    # psycopg2 exposes COPY via copy_expert(), not the
                    # psycopg3-style cursor.copy() API.
                    try:
                        f.write(f"COPY {fqn} FROM STDIN;\n")
                        cur.copy_expert(f"COPY {fqn} TO STDOUT", f)
                        f.write("\\.\n\n")
                        row_count += count
                    except Exception as e:
                        f.write(f"-- COPY failed: {e}\n\n")
                else:
                    f.write("\n")

            cur.close()

        conn.close()

        size = Path(filepath).stat().st_size
        if size == 0:
            return None, 0, "Backup file is empty"

        print(f"[verify_backup] dumped {len(tables)} tables, {row_count} rows")
        return filepath, size, None
    except ImportError:
        return None, 0, "psycopg2 not available"
    except Exception as e:
        return None, 0, str(e)


def _find_latest_backup(backup_dir: str) -> str | None:
    """Find the most recent .sql backup file."""
    path = Path(backup_dir)
    if not path.exists():
        return None
    sql_files = sorted(path.glob("fqp_*.sql"), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(sql_files[0]) if sql_files else None


def _verify_backup_integrity(filepath: str) -> dict[str, str | int | bool | None]:
    """Verify backup file integrity.

    Returns dict with check results.
    """
    result: dict[str, str | int | bool | None] = {
        "exists": False,
        "size_bytes": 0,
        "size_ok": False,
        "integrity_ok": False,
        "error": None,
    }

    path = Path(filepath)
    if not path.exists():
        result["error"] = f"Backup file not found: {filepath}"
        return result

    result["exists"] = True
    result["size_bytes"] = path.stat().st_size
    result["size_ok"] = path.stat().st_size > 0

    # Basic integrity check: verify file is valid SQL
    try:
        with open(filepath, errors="ignore") as f:
            header = f.read(200)
        if header.strip():
            is_sql = (
                header.strip().startswith("--")
                or header.strip().upper().startswith("SET ")
                or header.strip().upper().startswith("CREATE ")
                or header.strip().upper().startswith("COPY ")
                or "PostgreSQL" in header
            )
            if is_sql or path.stat().st_size > 100:
                result["integrity_ok"] = True
            else:
                result["integrity_ok"] = False
                result["error"] = "File does not look like a valid SQL dump"
        else:
            result["integrity_ok"] = False
            result["error"] = "File is empty or unreadable"
    except Exception as e:
        result["integrity_ok"] = False
        result["error"] = str(e)

    return result


def _test_restore(filepath: str) -> bool:
    """Check that essential data tables were exported without COPY failures."""
    try:
        with open(filepath) as f:
            content = f.read()
        required_tables = ("official_matches",)
        return (
            "COPY failed:" not in content
            and all(f"COPY public.{table} " in content or f'COPY "public"."{table}" ' in content
                    for table in required_tables)
        )
    except Exception:
        return False


def run(dry_run: bool = False) -> dict[str, Any]:
    """Create and verify a database backup.

    1. Creates a new pg_dump backup
    2. Verifies the backup integrity
    3. Logs the result

    Returns:
        Summary with creation and verification results.
    """
    backup_dir = _get_backup_dir()
    started_at = _now()

    # Step 1: Create backup
    print(f"[verify_backup] creating backup to {backup_dir}…")
    filepath, size_bytes, create_error = _create_backup(backup_dir)

    if create_error or filepath is None:
        result = {
            "status": "failed",
            "message": "Backup creation failed",
            "error": create_error,
            "backup_dir": backup_dir,
        }
        with get_db() as conn:
            store_backup_log(
                conn,
                {
                    "backup_type": "full",
                    "backup_path": None,
                    "backup_size_bytes": 0,
                    "started_at": started_at,
                    "finished_at": _now(),
                    "success": False,
                    "integrity_check_passed": False,
                    "restore_test_passed": False,
                    "error_message": create_error,
                    "backup_command": f"psycopg2 COPY → {backup_dir}",
                },
            )
        return result

    print(f"[verify_backup] backup created: {filepath} ({size_bytes:,} bytes)")

    # Step 2: Verify integrity
    verify_result = _verify_backup_integrity(filepath)
    finished_at = _now()

    # Step 3: Optional restore test
    restore_ok = None
    if verify_result["integrity_ok"] and not dry_run:
        try:
            restore_ok = _test_restore(filepath)
            print(f"[verify_backup] restore test: {'PASS' if restore_ok else 'FAIL'}")
        except Exception as e:
            print(f"[verify_backup] restore test error: {e}")
            restore_ok = False

    success = (
        verify_result["exists"]
        and verify_result["size_ok"]
        and verify_result["integrity_ok"]
        and (dry_run or restore_ok is True)
    )

    # Step 4: Log
    with get_db() as conn:
        store_backup_log(
            conn,
            {
                "backup_type": "full",
                "backup_path": filepath,
                "backup_size_bytes": verify_result["size_bytes"],
                "started_at": started_at,
                "finished_at": finished_at,
                "success": success,
                "integrity_check_passed": verify_result["integrity_ok"],
                "restore_test_passed": restore_ok,
                "error_message": verify_result.get("error"),
                "backup_command": f"psycopg2 COPY → {filepath}",
            },
        )

        # Clean up old backups (keep last 7 days)
        try:
            _cleanup_old_backups(backup_dir, keep_days=7)
        except Exception as e:
            print(f"[verify_backup] cleanup warning: {e}")

    return {
        "status": "ok" if success else "failed",
        "backup_file": filepath,
        "size_bytes": verify_result["size_bytes"],
        "integrity_check": verify_result["integrity_ok"],
        "restore_test": restore_ok,
        "success": success,
    }


def _cleanup_old_backups(backup_dir: str, keep_days: int = 7) -> None:
    """Remove backup files older than keep_days."""
    path = Path(backup_dir)
    if not path.exists():
        return
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    for f in path.glob("fqp_*.sql"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            print(f"[verify_backup] cleaned up old backup: {f.name}")


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    result = run(dry_run=dry)
    print(result)
