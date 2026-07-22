#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.local.yml"

# 01-32 predate the migration ledger and already form the baseline of existing
# local databases. New numbered files are applied once and recorded below.
BASELINE_VERSION=32

psql_exec() {
    docker compose -f "$COMPOSE_FILE" exec -T postgres \
        psql -X -U fqp -d fqp -v ON_ERROR_STOP=1 "$@"
}

# Register the legacy baseline in one database session. Starting a separate
# `docker compose exec` for every old file made each deploy look stalled.
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
