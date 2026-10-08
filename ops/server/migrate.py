"""Plan/apply incremental migrations as the application's database role.

Requires the existing checksum ledger; never guesses a production baseline.
Default is read-only planning. Use --apply only after copy dry-run and backup.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
from pathlib import Path

import psycopg2

ROOT = Path(__file__).resolve().parents[2]


def database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    for line in (ROOT / ".env.local").read_text().splitlines():
        key, sep, value = line.removeprefix("export ").partition("=")
        if sep and key.strip() == "DATABASE_URL":
            parts = shlex.split(value, comments=True)
            if len(parts) == 1:
                return parts[0]
    raise RuntimeError("DATABASE_URL is not configured")


def run(apply: bool) -> None:
    migrations = sorted(
        (path for path in (ROOT / "sql").glob("*.sql") if re.match(r"^\d+_", path.name)),
        key=lambda path: (int(path.name.split("_", 1)[0]), path.name),
    )
    with psycopg2.connect(database_url(), connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL timezone = 'UTC'")
            # Serialize planning and apply against other instances of this runner.
            cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (913201, 104))
            cur.execute(
                "SELECT current_user, datdba::regrole::text FROM pg_database WHERE datname = current_database()"
            )
            role, owner = cur.fetchone()
            if role != owner:
                raise RuntimeError("Connect as the application database owner, not postgres")
            cur.execute("SELECT filename, checksum_sha256 FROM local_schema_migrations")
            applied = dict(cur.fetchall())
            for filename in applied:
                if filename not in {path.name for path in migrations}:
                    raise RuntimeError(f"Applied migration is missing from checkout: {filename}")
            pending = []
            for path in migrations:
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                if path.name in applied:
                    if applied[path.name] is None:
                        raise RuntimeError(
                            f"Migration checksum baseline requires explicit review: {path.name}"
                        )
                    if applied[path.name] != checksum:
                        raise RuntimeError(f"Applied migration checksum changed: {path.name}")
                else:
                    pending.append((path, checksum))
            cur.execute("""
                SELECT c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                  AND (NOT has_table_privilege(current_user, c.oid, 'SELECT')
                    OR NOT has_table_privilege(current_user, c.oid, 'INSERT')
                    OR NOT has_table_privilege(current_user, c.oid, 'UPDATE'))
            """)
            if cur.fetchall():
                raise RuntimeError("Application role is missing table permissions")
            if apply:
                for path, checksum in pending:
                    print(f"Applying {path.name}", flush=True)
                    source = path.read_text()
                    if re.search(r"(?im)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", source):
                        raise RuntimeError(
                            f"Migration has its own transaction boundary: {path.name}"
                        )
                    cur.execute(source)
                    cur.execute(
                        "INSERT INTO local_schema_migrations(filename, checksum_sha256) VALUES (%s, %s)",
                        (path.name, checksum),
                    )
            else:
                print(f"Role: {role}; pending migrations: {[path.name for path, _ in pending]}")
            cur.execute("""
                SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind = 'S'
                  AND NOT has_sequence_privilege(current_user, c.oid, 'USAGE')
            """)
            if cur.fetchall():
                raise RuntimeError("Application role is missing sequence permissions")
        if not apply:
            conn.rollback()
    print("Migration apply complete" if apply else "Read-only migration plan complete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        run(args.apply)
    except Exception as exc:
        # Driver errors may contain a credential-bearing DSN; avoid printing them.
        if isinstance(exc, RuntimeError):
            parser.exit(1, f"Migration refused: {exc}\n")
        parser.exit(1, f"Migration failed: {type(exc).__name__}; inspect private database logs\n")
