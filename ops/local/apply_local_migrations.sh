#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.local"
PSQL_BIN="${FQP_PSQL_BIN:-}"
if [[ -z "$PSQL_BIN" ]]; then
    PSQL_BIN="$(command -v psql || true)"
fi
PSQL_BIN="${PSQL_BIN:-/opt/homebrew/opt/postgresql@18/bin/psql}"

# 01-32 predate the migration ledger and already form the baseline of existing
# local databases. New numbered files are applied once and recorded below.
BASELINE_VERSION=32

psql_exec() {
    "$PSQL_BIN" -X "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
}

psql_admin() {
    if [[ -n "${FQP_POSTGRES_ADMIN_PASSWORD:-}" ]]; then
        PGPASSWORD="$FQP_POSTGRES_ADMIN_PASSWORD" "$PSQL_BIN" -X -h 127.0.0.1 -p 5432 \
            -U "$ADMIN_USER" -v ON_ERROR_STOP=1 "$@"
    else
        env -u PGPASSWORD "$PSQL_BIN" -X -h 127.0.0.1 -p 5432 -U "$ADMIN_USER" \
            -v ON_ERROR_STOP=1 "$@"
    fi
}

migration_checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

ordered_migrations() {
    local migration filename version
    for migration in "$PROJECT_ROOT"/sql/*.sql; do
        filename="$(basename "$migration")"
        [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
        version=$((10#${BASH_REMATCH[1]}))
        printf '%s\t%s\n' "$version" "$migration"
    done | sort -n -k1,1 | cut -f2-
}

[[ -f "$ENV_FILE" ]] || { echo "[fqp-db] missing $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
set +u
source "$ENV_FILE"
set -u
set +a
ADMIN_USER="${FQP_POSTGRES_ADMIN_USER:-$USER}"
[[ "$DATABASE_URL" == *"@127.0.0.1:5432/fqp" ]] \
    || { echo "[fqp-db] native DATABASE_URL is required" >&2; exit 1; }

# P105's SECURITY DEFINER notifications and object ownership use a dedicated
# non-login role. Only the local PostgreSQL administrator can prepare it.
psql_admin -d postgres <<'SQL' >/dev/null
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND rolsuper) THEN
    RAISE EXCEPTION 'local migration bootstrap requires a PostgreSQL superuser';
  END IF;
END $$;
SELECT 'CREATE ROLE fqp_observation_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS'
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp_observation_owner') \gexec
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fqp_observation_owner'
      AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)) THEN
    RAISE EXCEPTION 'fqp_observation_owner exists with unsafe role attributes';
  END IF;
END $$;
SQL
psql_admin -d fqp -c 'GRANT USAGE, CREATE ON SCHEMA public TO fqp_observation_owner' >/dev/null

# All timestamp-without-time-zone audit fields use UTC storage semantics.
# Enforce the database default on every deployment, including migrated native
# databases that inherited the host's Asia/Shanghai timezone.
psql_exec -q <<'SQL'
SELECT format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC') \gexec
SET timezone TO 'UTC';
SQL

# Register the legacy baseline in one native database session.
{
    cat <<'SQL'
BEGIN;
CREATE TABLE IF NOT EXISTS local_schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum_sha256 TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE local_schema_migrations
    ADD COLUMN IF NOT EXISTS checksum_sha256 TEXT;
SQL
    while IFS= read -r migration; do
        filename="$(basename "$migration")"
        [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
        version=$((10#${BASH_REMATCH[1]}))
        if (( version <= BASELINE_VERSION )); then
            printf "INSERT INTO local_schema_migrations (filename) VALUES ('%s') ON CONFLICT DO NOTHING;\n" "$filename"
        fi
    done < <(ordered_migrations)
    printf 'COMMIT;\n'
} | psql_exec -q

# Existing ledgers predate checksums. Accept the current repository once as the
# baseline, then fail closed whenever an applied migration is edited later.
while IFS= read -r migration; do
    filename="$(basename "$migration")"
    checksum="$(migration_checksum "$migration")"
    psql_exec -q -v filename="$filename" -v checksum="$checksum" <<'SQL'
UPDATE local_schema_migrations
SET checksum_sha256 = :'checksum'
WHERE filename = :'filename'
  AND checksum_sha256 IS NULL;
SQL
done < <(ordered_migrations)

while IFS= read -r migration; do
    filename="$(basename "$migration")"
    [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
    version=$((10#${BASH_REMATCH[1]}))

    checksum="$(migration_checksum "$migration")"
    stored_checksum="$(psql_exec -Atq -v filename="$filename" <<'SQL'
SELECT checksum_sha256
FROM local_schema_migrations
WHERE filename = :'filename';
SQL
)"
    if [[ -n "$stored_checksum" ]]; then
        if [[ "$stored_checksum" != "$checksum" ]]; then
            echo "[fqp-db] applied migration was modified: $filename" >&2
            exit 1
        fi
        continue
    fi

    (( version <= BASELINE_VERSION )) && continue

    echo "[fqp-db] applying $filename"
    if grep -q 'FQP: CONCURRENT_INDEX' "$migration"; then
        index_name="$(sed -nE 's/^[[:space:]]*--[[:space:]]*FQP:[[:space:]]*CONCURRENT_INDEX[[:space:]]+([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*$/\1/p' "$migration")"
        [[ "$index_name" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] \
            || { echo "[fqp-db] malformed concurrent-index marker: $filename" >&2; exit 1; }
        [[ "$(grep -c 'FQP: CONCURRENT_INDEX' "$migration")" == "1" ]] \
            || { echo "[fqp-db] expected one concurrent-index marker: $filename" >&2; exit 1; }
        grep -Eq "CREATE[[:space:]]+INDEX[[:space:]]+CONCURRENTLY[[:space:]]+IF[[:space:]]+NOT[[:space:]]+EXISTS[[:space:]]+$index_name[[:space:]]+ON[[:space:]]+public\\.ai_job_runs" "$migration" \
            || { echo "[fqp-db] marked file does not create its declared index: $filename" >&2; exit 1; }
        {
            printf 'SELECT pg_advisory_lock(913201, 104);\n'
            printf "SELECT EXISTS (SELECT 1 FROM local_schema_migrations WHERE filename='%s') AS fqp_migration_exists, COALESCE((SELECT checksum_sha256='%s' FROM local_schema_migrations WHERE filename='%s'), FALSE) AS fqp_migration_checksum_matches\n" "$filename" "$checksum" "$filename"
            printf '\\gset\n'
            printf '\\if :fqp_migration_exists\n'
            printf '  \\if :fqp_migration_checksum_matches\n'
            printf '    \\echo [fqp-db] migration completed by another runner; skipping\n'
            printf '  \\else\n'
            printf '    \\echo [fqp-db] applied migration checksum differs: %s\n' "$filename"
            printf '%s\n' "    DO \$\$ BEGIN RAISE EXCEPTION 'FQP migration checksum differs: $filename'; END \$\$;"
            printf '  \\endif\n'
            printf '\\else\n'
            printf "SELECT format('DROP INDEX CONCURRENTLY IF EXISTS %%I.%%I', n.nspname, c.relname)\n"
            printf "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace\n"
            printf "JOIN pg_index i ON i.indexrelid=c.oid\n"
            printf "WHERE n.nspname='public' AND c.relname='%s'\n" "$index_name"
            printf "AND (NOT i.indisvalid OR NOT i.indisready)\n\\gexec\n"
            sed -n '1,$p' "$migration"
            printf "\nINSERT INTO local_schema_migrations (filename, checksum_sha256) VALUES ('%s', '%s');\n" "$filename" "$checksum"
            printf '\\endif\n'
            printf 'SELECT pg_advisory_unlock(913201, 104);\n'
        } | psql_exec -q
    else
        {
            printf 'BEGIN;\n'
            sed -n '1,$p' "$migration"
            printf "\nINSERT INTO local_schema_migrations (filename, checksum_sha256) VALUES ('%s', '%s');\n" "$filename" "$checksum"
            printf 'COMMIT;\n'
        } | if [[ "$filename" =~ ^(109|110)_ ]]; then
            psql_admin -d fqp -q
        else
            psql_exec -q
        fi
    fi
done < <(ordered_migrations)

echo "[fqp-db] incremental migrations are current"
