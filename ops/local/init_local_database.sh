#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
POSTGRES_BIN="${FQP_POSTGRES_BIN:-/opt/homebrew/opt/postgresql@18/bin}"
DATABASE_NAME="${FQP_DATABASE_NAME:-fqp}"
DATABASE_USER="${FQP_DATABASE_USER:-fqp}"
DATABASE_PASSWORD="${FQP_DATABASE_PASSWORD:-fqp_local_password}"
PORT="${FQP_POSTGRES_PORT:-5432}"
ADMIN_USER="${FQP_POSTGRES_ADMIN_USER:-$USER}"

[[ "$DATABASE_NAME" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || {
  echo "Invalid database name: $DATABASE_NAME" >&2
  exit 1
}
[[ "$DATABASE_USER" =~ ^[a-zA-Z_][a-zA-Z0-9_]*$ ]] || {
  echo "Invalid database user: $DATABASE_USER" >&2
  exit 1
}

for command_name in psql pg_isready createdb; do
  [[ -x "$POSTGRES_BIN/$command_name" ]] || {
    echo "Missing PostgreSQL tool: $POSTGRES_BIN/$command_name" >&2
    exit 1
  }
done

"$POSTGRES_BIN/pg_isready" -h 127.0.0.1 -p "$PORT" >/dev/null 2>&1 || {
  echo "PostgreSQL is not accepting connections on 127.0.0.1:$PORT." >&2
  exit 1
}

escaped_password="${DATABASE_PASSWORD//\'/\'\'}"
"$POSTGRES_BIN/psql" -h 127.0.0.1 -p "$PORT" -U "$ADMIN_USER" -d postgres \
  -v ON_ERROR_STOP=1 -v role_name="$DATABASE_USER" -v role_password="$escaped_password" <<'SQL' >/dev/null
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role_name', :'role_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role_name') \gexec
SQL

database_created=0
if ! "$POSTGRES_BIN/psql" -h 127.0.0.1 -p "$PORT" -U "$ADMIN_USER" -d postgres \
  -Atq -c "SELECT 1 FROM pg_database WHERE datname = '$DATABASE_NAME'" | grep -q '^1$'; then
  "$POSTGRES_BIN/createdb" -h 127.0.0.1 -p "$PORT" -U "$ADMIN_USER" \
    -O "$DATABASE_USER" "$DATABASE_NAME"
  database_created=1
fi

if (( database_created == 1 )); then
  export PGPASSWORD="$DATABASE_PASSWORD"
  for migration in "$PROJECT_ROOT"/sql/*.sql; do
    echo "[fqp-db] applying $(basename "$migration")"
    "$POSTGRES_BIN/psql" -h 127.0.0.1 -p "$PORT" -U "$DATABASE_USER" \
      -d "$DATABASE_NAME" -v ON_ERROR_STOP=1 -f "$migration" >/dev/null
  done

  {
    printf '%s\n' \
      'CREATE TABLE IF NOT EXISTS local_schema_migrations (' \
      'filename TEXT PRIMARY KEY,' \
      'applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()' \
      ');'
    for migration in "$PROJECT_ROOT"/sql/*.sql; do
      filename="$(basename "$migration")"
      printf "INSERT INTO local_schema_migrations (filename) VALUES ('%s') ON CONFLICT DO NOTHING;\n" "$filename"
    done
  } | "$POSTGRES_BIN/psql" -h 127.0.0.1 -p "$PORT" -U "$DATABASE_USER" \
    -d "$DATABASE_NAME" -v ON_ERROR_STOP=1 -q
fi

echo "[fqp-db] native database is ready: $DATABASE_NAME owner=$DATABASE_USER port=$PORT"
