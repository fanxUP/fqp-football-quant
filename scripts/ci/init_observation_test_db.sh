#!/usr/bin/env bash
# Disposable CI fixtures only. This is not a production role/migration script.
set -euo pipefail

if [[ "${FQP_ALLOW_ISOLATED_OBSERVATION_SETUP:-}" != "1" ||
      "${PGHOST:-}" != "127.0.0.1" || "${PGPORT:-}" != "5432" ||
      "${PGUSER:-}" != "fqp" || "${PGDATABASE:-}" != "fqp_test" ]]; then
  printf '%s\n' 'Refusing observation setup outside the explicit isolated CI database.' >&2
  exit 2
fi

export PGCONNECT_TIMEOUT=3
export PGOPTIONS='-c statement_timeout=15000 -c lock_timeout=2000'

psql -X -v ON_ERROR_STOP=1 <<'SQL'
DO $$
BEGIN
    IF current_database() <> 'fqp_test' OR current_user <> 'fqp'
       OR current_setting('server_version_num')::int / 10000 <> 16 THEN
        RAISE EXCEPTION 'Expected isolated PG16 CI source database';
    END IF;
    IF EXISTS (SELECT FROM official_matches)
       OR EXISTS (SELECT FROM observation_streams)
       OR EXISTS (SELECT FROM observation_cutoffs)
       OR EXISTS (SELECT FROM feature_batches) THEN
        RAISE EXCEPTION 'Fixture setup requires an empty business schema';
    END IF;
    IF EXISTS (SELECT FROM pg_database WHERE datname='fqp_observation_test')
       OR EXISTS (SELECT FROM pg_roles WHERE rolname IN (
           'fqp_observation_test','fqp_observation_reader',
           'fqp_observation_writer','fqp_player_writer')) THEN
        RAISE EXCEPTION 'Refusing to overwrite existing fixture database or roles';
    END IF;
END $$;
-- Public dummy credential, used only inside the disposable CI service.
CREATE ROLE fqp_observation_test LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS PASSWORD 'fqp_test_password';
SQL

createdb --owner=fqp_observation_test fqp_observation_test
pg_dump --schema-only --no-owner --no-privileges \
  | PGUSER=fqp_observation_test PGDATABASE=fqp_observation_test \
    psql -X -v ON_ERROR_STOP=1

psql -X -v ON_ERROR_STOP=1 -d fqp_observation_test <<'SQL'
BEGIN;
COMMENT ON DATABASE fqp_observation_test IS 'fqp-p104-isolated-fixtures/v1';
CREATE ROLE fqp_observation_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
CREATE ROLE fqp_observation_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
CREATE ROLE fqp_player_writer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS;
GRANT fqp_observation_writer,fqp_observation_reader,fqp_player_writer TO fqp_observation_test;

GRANT SELECT,INSERT ON observation_streams,observation_revisions,observation_checks,
    observation_cutoffs,feature_batches TO fqp_observation_writer;
GRANT USAGE ON SEQUENCE observation_streams_id_seq,observation_revisions_id_seq,
    observation_checks_id_seq,feature_batches_id_seq TO fqp_observation_writer;
GRANT SELECT ON observation_streams,observation_revisions,observation_checks,
    observation_cutoffs,feature_batches TO fqp_observation_reader;

GRANT SELECT,INSERT ON observation_streams,observation_revisions,observation_checks,
    observation_cutoffs TO fqp_player_writer;
GRANT SELECT,INSERT,UPDATE ON players,match_lineup_snapshots TO fqp_player_writer;
GRANT SELECT,INSERT,DELETE ON match_lineup_players TO fqp_player_writer;
GRANT SELECT,INSERT,UPDATE,DELETE ON player_availability_snapshots TO fqp_player_writer;
GRANT SELECT,INSERT ON team_squad_snapshots TO fqp_player_writer;
GRANT SELECT ON official_matches,teams,competition_seasons TO fqp_player_writer;
GRANT USAGE ON SEQUENCE players_id_seq,match_lineup_snapshots_id_seq,
    match_lineup_players_id_seq,player_availability_snapshots_id_seq,
    team_squad_snapshots_id_seq,observation_streams_id_seq,
    observation_revisions_id_seq,observation_checks_id_seq TO fqp_player_writer;

ALTER ROLE fqp_observation_test IN DATABASE fqp_observation_test SET statement_timeout='5s';
ALTER ROLE fqp_observation_test IN DATABASE fqp_observation_test SET lock_timeout='500ms';
COMMIT;
SQL
