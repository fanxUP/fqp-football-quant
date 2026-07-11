#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DATABASE_NAME="${FQP_DATABASE_NAME:-fqp}"
DATABASE_USER="${FQP_DATABASE_USER:-$USER}"
PORT="${FQP_POSTGRES_PORT:-5432}"

command -v psql >/dev/null 2>&1 || {
  echo "PostgreSQL client not found. Install and start a host PostgreSQL service first." >&2
  exit 1
}
command -v pg_isready >/dev/null 2>&1 || {
  echo "pg_isready not found. Install the PostgreSQL client tools first." >&2
  exit 1
}

pg_isready -h 127.0.0.1 -p "$PORT" >/dev/null 2>&1 || {
  echo "PostgreSQL is not accepting connections on 127.0.0.1:$PORT." >&2
  exit 1
}

createdb -h 127.0.0.1 -p "$PORT" -O "$DATABASE_USER" "$DATABASE_NAME" 2>/dev/null || {
  psql -h 127.0.0.1 -p "$PORT" -U "$DATABASE_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME'" >/dev/null || {
      echo "Unable to create or find database $DATABASE_NAME." >&2
      exit 1
    }
}

for schema in "$PROJECT_ROOT"/sql/*.sql; do
  echo "[fqp-db] importing $(basename "$schema")"
  psql -h 127.0.0.1 -p "$PORT" -U "$DATABASE_USER" -d "$DATABASE_NAME" -v ON_ERROR_STOP=1 -f "$schema" >/dev/null
done

echo "[fqp-db] initialized $DATABASE_NAME"
