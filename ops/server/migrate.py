"""Plan migrations with the configured role; apply pending SQL as owner/admin.

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
from psycopg2 import sql

ROOT = Path(__file__).resolve().parents[2]
TRANSACTION_CONTROL = re.compile(
    r"^\s*(BEGIN|START\s+TRANSACTION|COMMIT|END|ROLLBACK|ABORT|SAVEPOINT|RELEASE|"
    r"PREPARE\s+TRANSACTION)\b",
    re.IGNORECASE,
)
TRANSACTION_WRAPPER = re.compile(r"^\s*(BEGIN|COMMIT)\s*$", re.IGNORECASE)
CONCURRENT_INDEX_MARKER = re.compile(
    r"^[ \t]*--[ \t]*FQP:[ \t]*CONCURRENT_INDEX[ \t]+([A-Za-z_][A-Za-z0-9_]*)[ \t]*$",
    re.MULTILINE,
)


def _identifier_character(char: str) -> bool:
    return char.isalnum() or char in "_$" or ord(char) >= 128


def _dollar_quote_delimiter(source: str, index: int) -> str | None:
    if source[index] != "$":
        return None
    closing = source.find("$", index + 1)
    if closing < 0:
        return None
    tag = source[index + 1 : closing]
    if not tag:
        return "$$"
    if not (tag[0].isalpha() or tag[0] == "_" or ord(tag[0]) >= 128):
        return None
    if all(char.isalnum() or char == "_" or ord(char) >= 128 for char in tag):
        return source[index : closing + 1]
    return None


def _sql_statements(source: str) -> list[tuple[int, int, int, str]]:
    """Split SQL at top-level semicolons, hiding comments and quoted contents."""
    cleaned = list(source)
    statements: list[tuple[int, int, int, str]] = []
    segment_start = 0
    index = 0
    block_depth = 0
    mode = "normal"
    dollar_delimiter = ""
    single_quote_backslash_escape = False

    def blank(start: int, end: int) -> None:
        for position in range(start, end):
            if source[position] not in "\r\n":
                cleaned[position] = " "

    def append_statement(end: int) -> None:
        raw = "".join(cleaned[segment_start:end])
        command_start = segment_start
        while command_start < end and raw[command_start - segment_start].isspace():
            command_start += 1
        if raw.strip():
            statements.append((segment_start, end, command_start, raw))

    while index < len(source):
        char = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if mode == "line_comment":
            if char in "\r\n":
                mode = "normal"
            else:
                blank(index, index + 1)
            index += 1
            continue
        if mode == "block_comment":
            if char == "/" and following == "*":
                block_depth += 1
                blank(index, index + 2)
                index += 2
            elif char == "*" and following == "/":
                block_depth -= 1
                blank(index, index + 2)
                index += 2
                if block_depth == 0:
                    mode = "normal"
            else:
                blank(index, index + 1)
                index += 1
            continue
        if mode == "single_quote":
            blank(index, index + 1)
            if char == "'" and following == "'":
                blank(index + 1, index + 2)
                index += 2
            elif char == "'":
                mode = "normal"
                index += 1
            elif single_quote_backslash_escape and char == "\\" and index + 1 < len(source):
                blank(index + 1, index + 2)
                index += 2
            else:
                index += 1
            continue
        if mode == "double_quote":
            blank(index, index + 1)
            if char == '"' and following == '"':
                blank(index + 1, index + 2)
                index += 2
            elif char == '"':
                mode = "normal"
                index += 1
            else:
                index += 1
            continue
        if mode == "dollar_quote":
            closing = source.find(dollar_delimiter, index)
            if closing < 0:
                blank(index, len(source))
                index = len(source)
            else:
                blank(index, closing + len(dollar_delimiter))
                index = closing + len(dollar_delimiter)
                mode = "normal"
            continue

        if char == "-" and following == "-":
            blank(index, index + 2)
            index += 2
            mode = "line_comment"
        elif char == "/" and following == "*":
            blank(index, index + 2)
            index += 2
            block_depth = 1
            mode = "block_comment"
        elif char == "'":
            blank(index, index + 1)
            single_quote_backslash_escape = (
                index > 0
                and source[index - 1] in "eE"
                and (index < 2 or not _identifier_character(source[index - 2]))
            )
            index += 1
            mode = "single_quote"
        elif char == '"':
            blank(index, index + 1)
            index += 1
            mode = "double_quote"
        elif char == "$":
            delimiter = _dollar_quote_delimiter(source, index)
            preceded_by_identifier = index > 0 and _identifier_character(source[index - 1])
            if delimiter and not preceded_by_identifier:
                dollar_delimiter = delimiter
                blank(index, index + len(delimiter))
                index += len(delimiter)
                mode = "dollar_quote"
            else:
                index += 1
        elif char == ";":
            append_statement(index + 1)
            segment_start = index + 1
            index += 1
        else:
            index += 1

    if mode in {"block_comment", "single_quote", "double_quote", "dollar_quote"}:
        raise RuntimeError("Migration SQL has an unterminated comment or quoted value")
    append_statement(len(source))
    for start, end, _, cleaned_statement in statements:
        raw = source[start:end]
        changes_string_mode = (
            (
                re.match(r"^\s*(SET|RESET)\b", cleaned_statement, re.IGNORECASE)
                and "standard_conforming_strings" in raw.lower()
            )
            or re.match(r"^\s*RESET\s+ALL\b", cleaned_statement, re.IGNORECASE)
            or (
                re.search(r"\bset_config\s*\(", raw, re.IGNORECASE)
                and "standard_conforming_strings" in raw.lower()
            )
        )
        if changes_string_mode:
            raise RuntimeError("Migration cannot change standard_conforming_strings")
    return statements


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


def peer_migration_database_url(configured_dsn: str | None = None) -> str:
    """Build a local peer-authenticated DSN without carrying app credentials."""
    ambient_route = {
        "PGHOSTADDR",
        "PGSERVICE",
        "PGSERVICEFILE",
    }.intersection(os.environ)
    if ambient_route:
        names = ", ".join(sorted(ambient_route))
        raise RuntimeError(f"ambient libpq routing variables are unsupported: {names}")
    dsn = configured_dsn if configured_dsn is not None else database_url()
    parameters = psycopg2.extensions.parse_dsn(dsn)
    database_name = parameters.get("dbname")
    if not database_name or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", database_name):
        raise RuntimeError("DATABASE_URL must name a simple local database for peer migration")
    if parameters.get("service") or parameters.get("servicefile"):
        raise RuntimeError("DATABASE_URL service routing is unsupported for peer migration")
    configured_hosts = parameters.get("host", "").split(",")
    if len(configured_hosts) != 1 or configured_hosts[0] not in {
        "127.0.0.1",
        "::1",
        "localhost",
        "/var/run/postgresql",
    }:
        raise RuntimeError("DATABASE_URL must use a supported local PostgreSQL endpoint")
    configured_addresses = parameters.get("hostaddr", "").split(",")
    if configured_addresses != [""] and (
        len(configured_addresses) != 1 or configured_addresses[0] not in {"127.0.0.1", "::1"}
    ):
        raise RuntimeError("DATABASE_URL hostaddr must be a loopback address for peer migration")
    port = parameters.get("port", "")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise RuntimeError("DATABASE_URL must use one valid local PostgreSQL port")
    return psycopg2.extensions.make_dsn(
        dbname=database_name,
        user="postgres",
        host="/var/run/postgresql",
        port=port,
    )


def migration_body(source: str) -> str:
    """Keep outer transaction-wrapped SQL atomic with its checksum ledger row."""
    statements = _sql_statements(source)
    controls = []
    for statement_index, (_, end, command_start, cleaned) in enumerate(statements):
        transaction_match = TRANSACTION_CONTROL.match(cleaned)
        if transaction_match:
            wrapper_match = TRANSACTION_WRAPPER.fullmatch(cleaned.rstrip("; \t\r\n"))
            controls.append(
                (
                    statement_index,
                    transaction_match.group(1).upper(),
                    wrapper_match,
                    command_start,
                    end,
                )
            )
    if not controls:
        return source

    begin, commit = controls[0], controls[-1]
    if (
        len(controls) != 2
        or (begin[1], commit[1]) != ("BEGIN", "COMMIT")
        or begin[0] != 0
        or commit[0] != len(statements) - 1
        or begin[2] is None
        or commit[2] is None
    ):
        raise RuntimeError("Migration transaction boundary must wrap the entire file")

    body = list(source)
    for _, _, _, command_start, end in (commit, begin):
        for position in range(command_start, end):
            if body[position] not in "\r\n":
                body[position] = " "
    return "".join(body)


def concurrent_index_migration(source: str) -> tuple[str, str] | None:
    """Recognize the narrowly supported online-index migration format."""
    markers = list(CONCURRENT_INDEX_MARKER.finditer(source))
    if not markers:
        if re.search(r"FQP:\s*CONCURRENT_INDEX", source, re.IGNORECASE):
            raise RuntimeError("Malformed concurrent-index migration marker")
        return None
    if len(markers) != 1:
        raise RuntimeError("Concurrent-index migration must declare exactly one index")

    index_name = markers[0].group(1)
    statements = _sql_statements(source)
    if len(statements) != 1:
        raise RuntimeError("Concurrent-index migration must contain exactly one SQL statement")
    start, end, _, cleaned = statements[0]
    expected = re.compile(
        rf"^\s*CREATE\s+INDEX\s+CONCURRENTLY\s+IF\s+NOT\s+EXISTS\s+"
        rf"{re.escape(index_name)}\s+ON\s+public\.ai_job_runs\b",
        re.IGNORECASE,
    )
    if not expected.match(cleaned):
        raise RuntimeError("Marked migration must create its declared index concurrently")
    return index_name, source[start:end].strip()


def _concurrent_index_state(cur, index_name: str):
    cur.execute(
        """SELECT idx.indisvalid, idx.indisready, table_ns.nspname, table_rel.relname,
                  idx.indnatts, idx.indnkeyatts, am.amname,
                  pg_get_indexdef(index_rel.oid, 1, true),
                  pg_get_indexdef(index_rel.oid, 2, true),
                  pg_get_expr(idx.indpred, idx.indrelid)
           FROM pg_class index_rel
           JOIN pg_namespace index_ns ON index_ns.oid=index_rel.relnamespace
           JOIN pg_index idx ON idx.indexrelid=index_rel.oid
           JOIN pg_class table_rel ON table_rel.oid=idx.indrelid
           JOIN pg_namespace table_ns ON table_ns.oid=table_rel.relnamespace
           JOIN pg_am am ON am.oid=index_rel.relam
           WHERE index_ns.nspname='public' AND index_rel.relname=%s""",
        (index_name,),
    )
    return cur.fetchone()


def _validate_prediction_recovery_index(state, index_name: str) -> None:
    if state is None:
        raise RuntimeError(f"Concurrent index was not created: {index_name}")
    (
        valid,
        ready,
        schema,
        table,
        attributes,
        key_attributes,
        access_method,
        first_key,
        second_key,
        predicate,
    ) = state

    def normalize(value: str | None) -> str:
        return re.sub(r"[\s()\"]+", "", value or "").lower()

    expected_first_key = "input_snapshot_refs->>'execution_protocol'::text"
    expected_predicate_parts = ("job_code='model_prediction'", "status='running'")
    normalized_predicate = normalize(predicate)
    if (
        not valid
        or not ready
        or schema != "public"
        or table != "ai_job_runs"
        or attributes != 2
        or key_attributes != 2
        or access_method != "btree"
        or normalize(first_key) != expected_first_key
        or normalize(second_key) != "id"
        or not all(part in normalized_predicate for part in expected_predicate_parts)
    ):
        raise RuntimeError(f"Concurrent index definition or validity is unexpected: {index_name}")


def _apply_concurrent_index_migration(
    conn, *, filename: str, checksum: str, index_name: str, statement: str
) -> None:
    """Build one marked index outside a transaction and record it only when valid."""
    with conn.cursor() as cur:
        cur.execute("SHOW lock_timeout")
        previous_lock_timeout = cur.fetchone()[0]
        cur.execute("SHOW statement_timeout")
        previous_statement_timeout = cur.fetchone()[0]
        cur.execute("SET lock_timeout = '5s'")
        # A concurrent build can scan a large history table; it remains online
        # while keeping the deployment bounded and retryable after timeout.
        cur.execute("SET statement_timeout = '900s'")
        state = _concurrent_index_state(cur, index_name)
        if state is not None and (not state[0] or not state[1]):
            cur.execute(
                sql.SQL("DROP INDEX CONCURRENTLY IF EXISTS public.{} ").format(
                    sql.Identifier(index_name)
                )
            )
            state = None
        if state is None:
            cur.execute(statement)
            state = _concurrent_index_state(cur, index_name)
        _validate_prediction_recovery_index(state, index_name)
        cur.execute(
            "INSERT INTO local_schema_migrations(filename, checksum_sha256) VALUES (%s, %s)",
            (filename, checksum),
        )
        cur.execute("SELECT set_config('lock_timeout', %s, false)", (previous_lock_timeout,))
        cur.execute(
            "SELECT set_config('statement_timeout', %s, false)", (previous_statement_timeout,)
        )


def require_migration_authority(
    *, role: str, database_owner: str, superuser: bool, has_pending: bool, apply: bool
) -> None:
    if apply and has_pending and role != database_owner and not superuser:
        raise RuntimeError(
            "Apply pending migrations as the database owner or PostgreSQL administrator"
        )


def run(apply: bool) -> None:
    migrations = sorted(
        (path for path in (ROOT / "sql").glob("*.sql") if re.match(r"^\d+_", path.name)),
        key=lambda path: (int(path.name.split("_", 1)[0]), path.name),
    )
    conn = psycopg2.connect(database_url(), connect_timeout=5)
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SET LOCAL statement_timeout = '120s'")
            cur.execute("SET LOCAL standard_conforming_strings = on")
            cur.execute("SET LOCAL timezone = 'UTC'")
            # A session lock remains held while a marked index build temporarily
            # leaves transaction mode for CREATE INDEX CONCURRENTLY.
            cur.execute("SELECT pg_advisory_lock(%s, %s)", (913201, 104))
            cur.execute(
                """SELECT current_user, datdba::regrole::text,
                          (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
                   FROM pg_database WHERE datname = current_database()"""
            )
            role, owner, superuser = cur.fetchone()
            cur.execute("SELECT filename, checksum_sha256 FROM local_schema_migrations")
            applied = dict(cur.fetchall())
            known_migrations = {path.name for path in migrations}
            for filename in applied:
                if filename not in known_migrations:
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

        require_migration_authority(
            role=role,
            database_owner=owner,
            superuser=superuser,
            has_pending=bool(pending),
            apply=apply,
        )
        if apply:
            if pending and not superuser:
                # Migration 93 deliberately grants only SELECT/INSERT on its
                # append-only audit table; that remains an exception.
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT c.relname FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                          AND (NOT has_table_privilege(current_user, c.oid, 'SELECT')
                            OR NOT has_table_privilege(current_user, c.oid, 'INSERT')
                            OR (c.relname <> 'report_generation_revisions'
                                AND NOT has_table_privilege(current_user, c.oid, 'UPDATE')))
                    """)
                    if cur.fetchall():
                        raise RuntimeError("Application role is missing table permissions")
            for path, checksum in pending:
                print(f"Applying {path.name}", flush=True)
                source = path.read_text()
                concurrent_index = concurrent_index_migration(source)
                if concurrent_index is not None:
                    index_name, statement = concurrent_index
                    conn.commit()
                    conn.autocommit = True
                    try:
                        _apply_concurrent_index_migration(
                            conn,
                            filename=path.name,
                            checksum=checksum,
                            index_name=index_name,
                            statement=statement,
                        )
                    finally:
                        conn.autocommit = False
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (913201, 104))
                else:
                    with conn.cursor() as cur:
                        # Restore parser-sensitive settings after prior migrations.
                        cur.execute("SET LOCAL standard_conforming_strings = on")
                        cur.execute(migration_body(source))
                        cur.execute(
                            "INSERT INTO local_schema_migrations(filename, checksum_sha256) VALUES (%s, %s)",
                            (path.name, checksum),
                        )
            if pending and not superuser:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT relname FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relkind = 'S'
                          AND NOT has_sequence_privilege(current_user, c.oid, 'USAGE')
                    """)
                    if cur.fetchall():
                        raise RuntimeError("Application role is missing sequence permissions")
            conn.commit()
        else:
            print(f"Role: {role}; pending migrations: {[path.name for path, _ in pending]}")
            conn.rollback()
        print("Migration apply complete" if apply else "Read-only migration plan complete")
    finally:
        conn.close()


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
