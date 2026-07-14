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

psql_exec -q <<'SQL'
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
        psql_exec -q -c \
            "INSERT INTO local_schema_migrations (filename) VALUES ('$filename') ON CONFLICT DO NOTHING;"
        continue
    fi

    applied="$(psql_exec -Atq -c "SELECT 1 FROM local_schema_migrations WHERE filename = '$filename';")"
    [[ "$applied" == "1" ]] && continue

    echo "[fqp-db] applying $filename"
    {
        printf 'BEGIN;\n'
        sed -n '1,$p' "$migration"
        printf "\nINSERT INTO local_schema_migrations (filename) VALUES ('%s');\n" "$filename"
        printf 'COMMIT;\n'
    } | psql_exec -q
done

echo "[fqp-db] incremental migrations are current"
