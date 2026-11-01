"""Isolated rehearsal for migration 128 without copying production data."""

import hashlib
import os
from contextlib import closing
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import errors, sql
from psycopg2.extensions import parse_dsn

from ops.server.migrate import migration_body
from scripts.traditional_history_import import apply_issue_batch, load_issue_batch
from tests.test_jobs.test_traditional_history_import import _write_inputs

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = "128_traditional_history_facts.sql"


@pytest.fixture
def rehearsal_database():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN", "")
    if not dsn:
        pytest.skip("explicit disposable history database DSN not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_history_test_")

    role_created = False
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "no_backup_traditional_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname='fqp'")
            role = cur.fetchone()
            if role is None:
                cur.execute("CREATE ROLE fqp NOLOGIN NOSUPERUSER")
                role_created = True
            else:
                assert role[0] is False
            cur.execute(
                sql.SQL("CREATE SCHEMA {} AUTHORIZATION CURRENT_USER").format(
                    sql.Identifier(schema)
                )
            )
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE model_predictions(id BIGINT PRIMARY KEY)")
            for filename in (
                "01_core_official_schema.sql",
                "05_pool_reports_ops_schema.sql",
                "32_official_event_season_targets.sql",
                "117_pool_identity_and_snapshots.sql",
                "124_official_event_season_retention.sql",
                "125_football_fixture_identity.sql",
            ):
                source = (ROOT / "sql" / filename).read_text()
                cur.execute(migration_body(source))

            cur.execute(
                """INSERT INTO football_pool_issues(issue_no,game_type,total_matches)
                   VALUES ('26001','t14c',1) RETURNING id"""
            )
            issue_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO football_pool_issue_matches(
                       issue_id,match_order,league_name,home_team_name,away_team_name,kickoff_time
                   ) VALUES (%s,1,'Test League','Home','Away','2024-01-01 00:00:00')
                   RETURNING id""",
                (issue_id,),
            )
            member_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO football_pool_combinations(issue_id,combination_json)
                   VALUES (%s,'{"schema_version":"football-pool/v2","snapshot_hash":"before"}')""",
                (issue_id,),
            )
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
            cur.execute(
                "GRANT SELECT,INSERT,UPDATE ON football_pool_issues,football_pool_issue_matches TO fqp"
            )
            cur.execute(
                "GRANT USAGE,SELECT ON SEQUENCE football_pool_issues_id_seq,football_pool_issue_matches_id_seq TO fqp"
            )
            cur.execute("GRANT INSERT ON football_pool_fixture_revisions TO fqp")
            cur.execute(
                "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
            )
            baseline_migration = ROOT / "sql" / "125_football_fixture_identity.sql"
            cur.execute(
                "INSERT INTO local_schema_migrations(filename,checksum_sha256) VALUES (%s,%s)",
                (
                    baseline_migration.name,
                    hashlib.sha256(baseline_migration.read_bytes()).hexdigest(),
                ),
            )
        conn.commit()
        try:
            yield conn, schema, issue_id, member_id
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("RESET search_path")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if role_created:
                    cur.execute("DROP ROLE fqp")
            conn.commit()


def _legacy_snapshot(cur):
    cur.execute(
        """SELECT id,issue_no,game_type,source_game_type,sale_start_time,sale_stop_time,
                  total_matches,official_status,raw_hash,raw_json
           FROM football_pool_issues ORDER BY id"""
    )
    issues = cur.fetchall()
    cur.execute(
        """SELECT id,issue_id,match_order,match_id,fixture_id,identity_status,
                  identity_evidence,source_raw_json,source_match_id,league_name,
                  home_team_name,away_team_name,kickoff_time,home_win_prob,draw_prob,
                  away_win_prob,upset_score,public_heat_home,public_heat_draw,
                  public_heat_away
           FROM football_pool_issue_matches ORDER BY id"""
    )
    members = cur.fetchall()
    cur.execute("SELECT * FROM football_pool_combinations ORDER BY id")
    combinations = cur.fetchall()
    cur.execute("SELECT * FROM football_pool_fixture_revisions ORDER BY id")
    revisions = cur.fetchall()
    return issues, members, combinations, revisions


def test_128_is_additive_runtime_usable_and_transactionally_rollbackable(
    rehearsal_database, tmp_path
):
    conn, schema, issue_id, member_id = rehearsal_database
    migration_path = ROOT / "sql" / MIGRATION
    migration_sql = migration_body(migration_path.read_text())

    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('server_version_num')::int / 10000")
        postgres_major = cur.fetchone()[0]
        before = _legacy_snapshot(cur)
        cur.execute(
            "SELECT filename,checksum_sha256 FROM local_schema_migrations "
            "WHERE filename='125_football_fixture_identity.sql'"
        )
        baseline_receipt = cur.fetchone()
        assert baseline_receipt is not None
        cur.execute(migration_sql)
        cur.execute("SHOW lock_timeout")
        assert cur.fetchone()[0] == "2s"
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone()[0] == "30s"

        cur.execute(
            """SELECT kickoff_date,kickoff_time_precision,kickoff_evidence,
                      source_full_home_goals,source_product_result_code
               FROM football_pool_issue_matches WHERE id=%s""",
            (member_id,),
        )
        assert cur.fetchone() == (None, "unknown", {}, None, None)
        cur.execute(
            """SELECT source_game_no,source_game_no_source
               FROM football_pool_issues WHERE id=%s""",
            (issue_id,),
        )
        assert cur.fetchone() == (None, None)
        cur.execute(
            """SELECT count(*) FROM pg_constraint
               WHERE conrelid='football_pool_issue_matches'::regclass
                 AND conname IN ('pool_kickoff_precision','pool_kickoff_evidence_object',
                                 'pool_traditional_scores_nonnegative',
                                 'pool_traditional_result_evidence_object',
                                 'pool_traditional_result_semantics')
                 AND convalidated"""
        )
        assert cur.fetchone()[0] == 5
        cur.execute(
            """SELECT count(*) FROM pg_indexes
               WHERE schemaname=current_schema()
                 AND indexname='idx_pool_issue_match_kickoff_date'"""
        )
        assert cur.fetchone()[0] == 1
        assert _legacy_snapshot(cur) == before
        cur.execute(
            """SELECT count(*) FROM pg_trigger
               WHERE tgrelid='football_pool_issue_matches'::regclass
                 AND tgname='record_pool_fixture_revision' AND NOT tgisinternal"""
        )
        assert cur.fetchone()[0] == 1

        cur.execute("SET ROLE fqp")
        cur.execute(
            """SELECT membership_id,kickoff_date,kickoff_time_precision,
                      source_full_home_goals
               FROM football_pool_fixture_catalog WHERE issue_id=%s""",
            (issue_id,),
        )
        assert cur.fetchone() == (member_id, None, "unknown", None)
        cur.execute(
            """UPDATE football_pool_issue_matches
               SET kickoff_date='2024-01-01',kickoff_time_precision='date_only',
                   kickoff_evidence='{"source":"official_history_api"}',
                   source_full_home_goals=2,source_full_away_goals=1,
                   source_half_home_goals=1,source_half_away_goals=0,
                   source_product_result_code='3',
                   source_result_semantics_key='sporttery_history_api:90',
                   source_result_source='sporttery_history_api',
                   source_result_evidence='{"result":"3"}'
               WHERE id=%s""",
            (member_id,),
        )
        cur.execute(
            """UPDATE football_pool_issues
               SET source_game_no=90,source_game_no_source='sporttery_history_api'
               WHERE id=%s""",
            (issue_id,),
        )
        cur.execute(
            """SELECT issue_no,kickoff_date,kickoff_time_precision,
                      source_full_home_goals,source_product_result_code
               FROM football_pool_fixture_catalog WHERE issue_id=%s""",
            (issue_id,),
        )
        assert cur.fetchone() == ("26001", date(2024, 1, 1), "date_only", 2, "3")
        cur.execute("RESET ROLE")
        cur.execute(
            "SELECT count(*) FROM football_pool_fixture_revisions WHERE issue_id=%s", (issue_id,)
        )
        assert cur.fetchone()[0] > len(before[3])
        cur.execute("SELECT has_table_privilege('fqp','local_schema_migrations','SELECT')")
        assert cur.fetchone()[0] is True

        cur.execute("SAVEPOINT invalid_fact")
        with pytest.raises(errors.CheckViolation):
            cur.execute(
                "UPDATE football_pool_issues SET source_game_no=98 WHERE id=%s", (issue_id,)
            )
        cur.execute("ROLLBACK TO SAVEPOINT invalid_fact")
        cur.execute(
            "INSERT INTO local_schema_migrations(filename,checksum_sha256) VALUES (%s,%s)",
            (MIGRATION, hashlib.sha256(migration_path.read_bytes()).hexdigest()),
        )

    # Migration DDL, runtime writes and migration-ledger insertion share the
    # production runner's transaction and must all disappear on rollback.
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur.execute(
            "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s AND table_name='football_pool_issue_matches' AND column_name='kickoff_date'",
            (schema,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT to_regclass(%s)", (f"{schema}.idx_pool_issue_match_kickoff_date",))
        assert cur.fetchone()[0] is None
        assert _legacy_snapshot(cur) == before
        cur.execute(
            "SELECT filename,checksum_sha256 FROM local_schema_migrations ORDER BY filename"
        )
        assert cur.fetchall() == [baseline_receipt]

    # Reapply in the disposable schema as a committed migration, write its
    # exact ledger receipt, then exercise the real bounded importer as the
    # restricted application role rather than simulating its SQL manually.
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur.execute(migration_sql)
        cur.execute(
            "INSERT INTO local_schema_migrations(filename,checksum_sha256) VALUES (%s,%s)",
            (MIGRATION, hashlib.sha256(migration_path.read_bytes()).hexdigest()),
        )
        cur.execute("SELECT has_table_privilege('fqp','local_schema_migrations','SELECT')")
        assert cur.fetchone()[0] is True
    conn.commit()

    preview, manifest, summary = _write_inputs(tmp_path)
    batch = load_issue_batch(preview, manifest, summary, kind="new", limit=1)
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
    conn.commit()
    assert apply_issue_batch(conn, batch) == {
        "inserted_issues": 1,
        "inserted_members": 6,
        "already_imported_issues": 0,
    }
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("RESET ROLE")
        cur.execute(
            "SELECT source_game_no,source_game_no_source FROM football_pool_issues "
            "WHERE game_type='bqc6' AND issue_no='21062'"
        )
        assert cur.fetchone() == (98, "sporttery_history_api")
        cur.execute(
            "SELECT count(*) FROM football_pool_issue_matches im "
            "JOIN football_pool_issues i ON i.id=im.issue_id "
            "WHERE i.game_type='bqc6' AND i.issue_no='21062'"
        )
        assert cur.fetchone()[0] == 6
    conn.commit()
    assert postgres_major >= 15
