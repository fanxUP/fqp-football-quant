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
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
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

applied_files="$(psql_exec -Atq -c 'SELECT filename FROM local_schema_migrations ORDER BY filename;')"
applied_files=$'\n'"$applied_files"$'\n'

for migration in "$PROJECT_ROOT"/sql/*.sql; do
    filename="$(basename "$migration")"
    [[ "$filename" =~ ^([0-9]+)_.*\.sql$ ]] || continue
    version=$((10#${BASH_REMATCH[1]}))

    (( version <= BASELINE_VERSION )) && continue

    [[ "$applied_files" == *$'\n'"$filename"$'\n'* ]] && continue

    echo "[fqp-db] applying $filename"
    {
        printf 'BEGIN;\n'
        sed -n '1,$p' "$migration"
        printf "\nINSERT INTO local_schema_migrations (filename) VALUES ('%s');\n" "$filename"
        printf 'COMMIT;\n'
    } | psql_exec -q
done

echo "[fqp-db] incremental migrations are current"
