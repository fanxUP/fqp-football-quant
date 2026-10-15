#!/usr/bin/env bash
set -Eeuo pipefail

psql_admin() {
  PGPASSWORD="$FQP_POSTGRES_ADMIN_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" \
    -p "$PGPORT" -U postgres -d postgres "$@"
}

psql_app() {
  PGPASSWORD="$FQP_DATABASE_PASSWORD" psql -X -v ON_ERROR_STOP=1 -h "$PGHOST" \
    -p "$PGPORT" -U "$FQP_DATABASE_USER" -d "$FQP_DATABASE_NAME" "$@"
}

psql_admin -v role_name="$FQP_DATABASE_USER" -v role_password="$FQP_DATABASE_PASSWORD" \
  -v db_name="$FQP_DATABASE_NAME" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'role_name', :'role_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'role_name')
\gexec
SELECT format('CREATE DATABASE %I OWNER %I', :'db_name', :'role_name')
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db_name')
\gexec
SQL

psql_app <<'SQL'
SELECT format('ALTER DATABASE %I SET timezone TO %L', current_database(), 'UTC') \gexec
CREATE TABLE IF NOT EXISTS local_schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum_sha256 TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
SQL

mapfile -d '' migrations < <(
  find /migrations -maxdepth 1 -type f -regextype posix-extended \
    -regex '.*/[0-9]+_.*\.sql' -print0 | sort -zV
)

for migration in "${migrations[@]}"; do
  filename="$(basename "$migration")"
  checksum="$(sha256sum "$migration" | cut -d ' ' -f 1)"
  stored="$(psql_app -Atq -v filename="$filename" <<'SQL'
SELECT checksum_sha256 FROM local_schema_migrations WHERE filename = :'filename';
SQL
)"
  if [[ -n "$stored" ]]; then
    [[ "$stored" == "$checksum" ]] || { echo "Migration checksum mismatch: $filename" >&2; exit 1; }
    continue
  fi
  echo "[docker-test-db] applying $filename"
  psql_app -f "$migration"
  psql_app -v filename="$filename" -v checksum="$checksum" <<'SQL'
INSERT INTO local_schema_migrations(filename, checksum_sha256)
VALUES (:'filename', :'checksum');
SQL
done

echo "[docker-test-db] schema ready; applied $(psql_app -Atq -c 'SELECT count(*) FROM local_schema_migrations') migrations"
