"""Atomic rehearsal of the exact no-backup 124/125 migration set."""

import os
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extensions import parse_dsn

from ops.server.migrate import migration_body

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = (
    "124_official_event_season_retention.sql",
    "125_football_fixture_identity.sql",
)


@pytest.fixture
def rehearsal_database():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN", "")
    if not dsn:
        pytest.skip("explicit disposable history database DSN not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_history_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "no_backup_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {} ").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE model_predictions(id BIGINT PRIMARY KEY)")
            for filename in (
                "01_core_official_schema.sql",
                "05_pool_reports_ops_schema.sql",
                "32_official_event_season_targets.sql",
                "117_pool_identity_and_snapshots.sql",
            ):
                cur.execute((ROOT / "sql" / filename).read_text())
            cur.execute(
                """INSERT INTO official_event_season_targets(
                    league_name,season_name,season_start_date,season_end_date,
                    selection_reason,boundary_source,source_url,as_of_date
                ) VALUES ('Rehearsal League','2025/2026','2025-08-01','2026-05-31',
                    'current_started','sporttery','https://example.test/season','2026-10-30')"""
            )
            cur.execute(
                """INSERT INTO official_matches(
                    business_date,official_match_code,source_match_id,league_name,
                    home_team_name,away_team_name,kickoff_time
                ) VALUES ('2026-04-30','周四001','source-1','Rehearsal League',
                    'Home','Away','2026-04-30 19:00:00') RETURNING id"""
            )
            match_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO official_results(match_id,full_home_goals,full_away_goals) VALUES (%s,2,1)",
                (match_id,),
            )
            cur.execute(
                "INSERT INTO football_pool_issues(issue_no,game_type) VALUES ('26001','t14c') RETURNING id"
            )
            issue_id = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO football_pool_issue_matches(issue_id,match_order,match_id,
                    league_name,home_team_name,away_team_name,kickoff_time)
                    VALUES (%s,1,%s,'Rehearsal League','Home','Away','2026-04-30 19:00:00')""",
                (issue_id, match_id),
            )
            cur.execute(
                """INSERT INTO football_pool_combinations(issue_id,combination_json)
                    VALUES (%s,'{"schema_version":"football-pool/v2","snapshot_hash":"before"}')""",
                (issue_id,),
            )
            cur.execute(
                "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
            )
        conn.commit()
        try:
            yield conn, schema, match_id, issue_id
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET search_path")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()


def test_124_125_preserve_legacy_rows_and_rollback_as_one_transaction(rehearsal_database):
    conn, schema, match_id, issue_id = rehearsal_database
    snapshot_queries = {
        "official_matches": "SELECT * FROM official_matches ORDER BY 1",
        "official_results": "SELECT * FROM official_results ORDER BY 1",
        "football_pool_issues": "SELECT * FROM football_pool_issues ORDER BY 1",
        "football_pool_issue_matches": """SELECT id,issue_id,match_order,match_id,
            source_match_id,league_name,home_team_name,away_team_name,kickoff_time
            FROM football_pool_issue_matches ORDER BY id""",
        "football_pool_combinations": "SELECT * FROM football_pool_combinations ORDER BY 1",
        "official_event_season_targets": "SELECT * FROM official_event_season_targets ORDER BY 1",
    }
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting('server_version_num')::int / 10000")
        postgres_major = cur.fetchone()[0]
        before = {}
        for table, query in snapshot_queries.items():
            cur.execute(query)
            before[table] = cur.fetchall()

        for name in MIGRATIONS:
            path = ROOT / "sql" / name
            cur.execute(migration_body(path.read_text()))
            cur.execute(
                """INSERT INTO local_schema_migrations(filename,checksum_sha256)
                    VALUES (%s,encode(sha256(convert_to(%s,'UTF8')),'hex'))""",
                (name, path.read_text()),
            )

        cur.execute("SHOW lock_timeout")
        assert cur.fetchone()[0] == "2s"
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone()[0] == "30s"
        cur.execute("SELECT count(*) FROM official_event_season_retention")
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT id,match_id,fixture_id,identity_status FROM football_pool_issue_matches"
        )
        memberships = cur.fetchall()
        assert len(memberships) == 1
        assert memberships[0][1:] == (match_id, None, "pending")
        cur.execute("SELECT count(*) FROM football_fixtures")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM football_pool_fixture_revisions")
        assert cur.fetchone()[0] == 0
        cur.execute(
            """SELECT count(*) FROM pg_trigger
                WHERE tgrelid='football_pool_issue_matches'::regclass
                  AND tgname='record_pool_fixture_revision' AND NOT tgisinternal"""
        )
        assert cur.fetchone()[0] == 1
        for table, rows in before.items():
            cur.execute(snapshot_queries[table])
            assert cur.fetchall() == rows
        cur.execute("SELECT id FROM football_pool_issues")
        assert cur.fetchall() == [(issue_id,)]
        cur.execute("SELECT count(*) FROM local_schema_migrations")
        assert cur.fetchone()[0] == len(MIGRATIONS)

    # The production runner records each migration in the same outer transaction.
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s)", (f"{schema}.official_event_season_retention",))
        assert cur.fetchone()[0] is None
        cur.execute("SELECT to_regclass(%s)", (f"{schema}.football_fixtures",))
        assert cur.fetchone()[0] is None
        cur.execute(
            """SELECT count(*) FROM information_schema.columns
                WHERE table_schema=%s AND table_name='football_pool_issue_matches'
                  AND column_name='fixture_id'""",
            (schema,),
        )
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT count(*) FROM local_schema_migrations")
        assert cur.fetchone()[0] == 0
        for table, rows in before.items():
            cur.execute(snapshot_queries[table])
            assert cur.fetchall() == rows
        cur.execute("SELECT id FROM football_pool_issues")
        assert cur.fetchall() == [(issue_id,)]
    assert postgres_major >= 15
