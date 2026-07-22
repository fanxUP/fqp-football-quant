#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/.env.local"
PSQL_BIN="${FQP_PSQL_BIN:-/opt/homebrew/opt/postgresql@18/bin/psql}"

# 01-32 predate the migration ledger and already form the baseline of existing
# local databases. New numbered files are applied once and recorded below.
BASELINE_VERSION=32

psql_exec() {
    "$PSQL_BIN" -X "$DATABASE_URL" -v ON_ERROR_STOP=1 "$@"
}

migration_checksum() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

[[ -f "$ENV_FILE" ]] || { echo "[fqp-db] missing $ENV_FILE" >&2; exit 1; }
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
[[ "$DATABASE_URL" == *"@127.0.0.1:5432/fqp" ]] \
    || { echo "[fqp-db] native DATABASE_URL is required" >&2; exit 1; }

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
    for migration in "$PROJECT_ROOT"/sql/*.sql; do
        filename="$(basename "$migration")"
        [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
        version=$((10#${BASH_REMATCH[1]}))
        if (( version <= BASELINE_VERSION )); then
            printf "INSERT INTO local_schema_migrations (filename) VALUES ('%s') ON CONFLICT DO NOTHING;\n" "$filename"
        fi
    done
    printf 'COMMIT;\n'
} | psql_exec -q

# Existing ledgers predate checksums. Accept the current repository once as the
# baseline, then fail closed whenever an applied migration is edited later.
for migration in "$PROJECT_ROOT"/sql/*.sql; do
    filename="$(basename "$migration")"
    [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
    checksum="$(migration_checksum "$migration")"
    psql_exec -q -v filename="$filename" -v checksum="$checksum" <<'SQL'
UPDATE local_schema_migrations
SET checksum_sha256 = :'checksum'
WHERE filename = :'filename'
  AND checksum_sha256 IS NULL;
SQL
done

for migration in "$PROJECT_ROOT"/sql/*.sql; do
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
    {
        printf 'BEGIN;\n'
        sed -n '1,$p' "$migration"
        printf "\nINSERT INTO local_schema_migrations (filename, checksum_sha256) VALUES ('%s', '%s');\n" "$filename" "$checksum"
        printf 'COMMIT;\n'
    } | psql_exec -q
done

echo "[fqp-db] incremental migrations are current"
