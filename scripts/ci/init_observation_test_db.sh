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
           'fqp_observation_writer','fqp_player_writer','fqp_input_consumer')) THEN
        RAISE EXCEPTION 'Refusing to overwrite existing fixture database or roles';
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='fqp_observation_owner'
        AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
        AND NOT rolreplication AND NOT rolbypassrls) THEN
        RAISE EXCEPTION 'P105 no-login owner role is missing or unsafe';
    END IF;
    IF NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_dirty_matches'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type='SELECT'
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_dirty_matches'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type='UPDATE'
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_consumers'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type='SELECT'
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_consumers'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type IN ('INSERT','UPDATE')
        GROUP BY c.oid HAVING count(DISTINCT acl.privilege_type)=2
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_consumptions'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type IN ('SELECT','INSERT')
        GROUP BY c.oid HAVING count(DISTINCT acl.privilege_type)=2
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_revisions'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type IN ('SELECT','INSERT')
        GROUP BY c.oid HAVING count(DISTINCT acl.privilege_type)=2
    ) OR NOT EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid='public.prediction_input_revisions_id_seq'::regclass
          AND acl.grantee='fqp'::regrole AND acl.privilege_type='USAGE'
    ) THEN
        RAISE EXCEPTION 'P105 migrations did not grant the required runtime ACLs to fqp';
    END IF;
    IF EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE c.oid IN (
            'public.prediction_input_consumptions'::regclass,
            'public.prediction_input_revisions'::regclass
        ) AND acl.grantee='fqp'::regrole
          AND acl.privilege_type IN ('UPDATE','DELETE','TRUNCATE')
    ) THEN
        RAISE EXCEPTION 'P105 append-only runtime grants include mutation privileges';
    END IF;
    IF EXISTS (
        SELECT FROM pg_class c CROSS JOIN LATERAL aclexplode(c.relacl) acl
        WHERE acl.grantee='fqp'::regrole AND (
            (c.oid='public.prediction_input_dirty_matches'::regclass
                AND acl.privilege_type NOT IN ('SELECT','UPDATE'))
            OR (c.oid='public.prediction_input_consumers'::regclass
                AND acl.privilege_type NOT IN ('SELECT','INSERT','UPDATE'))
            OR (c.oid IN (
                'public.prediction_input_consumptions'::regclass,
                'public.prediction_input_revisions'::regclass
            ) AND acl.privilege_type NOT IN ('SELECT','INSERT'))
            OR (c.oid='public.prediction_input_revisions_id_seq'::regclass
                AND acl.privilege_type <> 'USAGE')
        )
    ) THEN
        RAISE EXCEPTION 'P105 runtime grants include privileges outside the required ACL';
    END IF;
    IF EXISTS (
        SELECT FROM pg_class c
        WHERE c.oid IN (
            'public.prediction_input_dirty_matches'::regclass,
            'public.prediction_input_consumers'::regclass,
            'public.prediction_input_consumptions'::regclass,
            'public.prediction_input_revisions'::regclass,
            'public.prediction_input_revisions_id_seq'::regclass
        ) AND c.relowner <> 'fqp_observation_owner'::regrole
    ) OR EXISTS (
        SELECT FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public'
          AND p.proname IN ('notify_prediction_input_update','notify_prediction_official_update')
          AND p.proowner <> 'fqp_observation_owner'::regrole
    ) THEN
        RAISE EXCEPTION 'P105 migration objects are not owned by the no-login observation owner';
    END IF;
    IF NOT has_table_privilege(
        'fqp_observation_owner','public.observation_streams','SELECT'
    ) THEN
        RAISE EXCEPTION 'P105 notification owner cannot read observation stream bindings';
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
GRANT USAGE,CREATE ON SCHEMA public TO fqp_observation_owner;
GRANT SELECT ON observation_streams TO fqp_observation_owner;
ALTER TABLE prediction_input_dirty_matches OWNER TO fqp_observation_owner;
ALTER TABLE prediction_input_consumers OWNER TO fqp_observation_owner;
ALTER TABLE prediction_input_consumptions OWNER TO fqp_observation_owner;
ALTER TABLE prediction_input_revisions OWNER TO fqp_observation_owner;
ALTER SEQUENCE prediction_input_revisions_id_seq OWNER TO fqp_observation_owner;
ALTER FUNCTION notify_prediction_input_update() OWNER TO fqp_observation_owner;
ALTER FUNCTION notify_prediction_official_update() OWNER TO fqp_observation_owner;
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

-- Older CI callers may stop at migration108; grant queue privileges only when
-- the additive migration109 is present. The P105 tests require these tables.
DO $$
BEGIN
    IF to_regclass('public.prediction_input_dirty_matches') IS NOT NULL THEN
        -- The schema clone omits ACLs; restore the migration's trigger-function
        -- restriction explicitly instead of inheriting PUBLIC EXECUTE defaults.
        REVOKE ALL ON FUNCTION notify_prediction_input_update() FROM PUBLIC;
        CREATE ROLE fqp_input_consumer NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
        GRANT fqp_input_consumer TO fqp_observation_test;
        GRANT SELECT ON prediction_input_dirty_matches,prediction_input_consumers,
            prediction_input_consumptions TO fqp_observation_reader;
        GRANT SELECT,UPDATE ON prediction_input_dirty_matches TO fqp_input_consumer;
        GRANT SELECT,INSERT,UPDATE ON prediction_input_consumers TO fqp_input_consumer;
        GRANT SELECT,INSERT ON prediction_input_consumptions TO fqp_input_consumer;
    END IF;
    IF to_regclass('public.prediction_input_revisions') IS NOT NULL THEN
        REVOKE ALL ON FUNCTION notify_prediction_official_update() FROM PUBLIC;
        GRANT SELECT ON prediction_input_revisions TO fqp_observation_reader;
        GRANT SELECT,INSERT ON prediction_input_revisions TO fqp_input_consumer;
        GRANT USAGE ON SEQUENCE prediction_input_revisions_id_seq TO fqp_input_consumer;
        GRANT SELECT ON official_matches,official_markets,official_odds_snapshots,teams,team_aliases,
            feature_batches,observation_streams,observation_revisions,observation_checks,
            observation_cutoffs TO fqp_input_consumer;
        GRANT INSERT ON observation_cutoffs,feature_batches TO fqp_input_consumer;
        GRANT USAGE ON SEQUENCE feature_batches_id_seq TO fqp_input_consumer;
        -- Test-only elevated actor rights exercise immutable triggers. The source
        -- database assertions above independently prove fqp's deployed ACL stays narrow.
        GRANT UPDATE,DELETE,TRUNCATE ON prediction_input_consumptions,
            prediction_input_revisions TO fqp_observation_writer;
        GRANT DELETE ON prediction_input_dirty_matches TO fqp_observation_writer;
    END IF;
END $$;

ALTER ROLE fqp_observation_test IN DATABASE fqp_observation_test SET statement_timeout='5s';
ALTER ROLE fqp_observation_test IN DATABASE fqp_observation_test SET lock_timeout='500ms';
COMMIT;
SQL
