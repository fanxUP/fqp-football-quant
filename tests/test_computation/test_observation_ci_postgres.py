"""CI fixture permissions and login defaults; never an application database."""

import os
from contextlib import closing

import psycopg2
import pytest

from tests.test_computation import test_observation_postgres as obs

connect = obs.connect
pg = obs.pg


def raw_connect(connect):
    # Validate the exact DSN/marker through the shared fixture before checking
    # login defaults without its explicit session timeout options.
    with closing(connect()):
        pass
    return psycopg2.connect(os.environ["FQP_OBSERVATION_TEST_POSTGRES_DSN"], connect_timeout=3)


def test_login_defaults_bound_statement_and_lock_time_without_fixture_options(connect):
    with closing(raw_connect(connect)) as conn, conn.cursor() as cur:
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone() == ("5s",)
        cur.execute("SHOW lock_timeout")
        assert cur.fetchone() == ("500ms",)


@pytest.mark.parametrize(
    ("role", "login"),
    [
        ("fqp_observation_test", True),
        ("fqp_observation_reader", False),
        ("fqp_observation_writer", False),
        ("fqp_player_writer", False),
    ],
)
def test_fixture_roles_have_no_cluster_administration_rights(pg, role, login):
    with pg.cursor() as cur:
        cur.execute(
            "SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls "
            "FROM pg_roles WHERE rolname=%s",
            (role,),
        )
        assert cur.fetchone() == (login, False, False, False, False, False)


@pytest.mark.parametrize(
    ("role", "insert", "batch_insert"),
    [
        ("fqp_observation_reader", False, False),
        ("fqp_observation_writer", True, True),
        ("fqp_player_writer", True, False),
    ],
)
def test_history_grants_are_select_insert_only(pg, role, insert, batch_insert):
    with pg.cursor() as cur:
        for table in (
            "observation_streams",
            "observation_revisions",
            "observation_checks",
            "observation_cutoffs",
            "feature_batches",
        ):
            cur.execute(
                "SELECT has_table_privilege(%s,%s,'SELECT'),"
                "has_table_privilege(%s,%s,'INSERT'),"
                "has_table_privilege(%s,%s,'UPDATE,DELETE,TRUNCATE')",
                (role, table) * 3,
            )
            assert cur.fetchone() == (
                not (role == "fqp_player_writer" and table == "feature_batches"),
                batch_insert if table == "feature_batches" else insert,
                False,
            )


def test_database_role_defaults_really_interrupt_blocked_read(pg, connect):
    with pg.cursor() as cur:
        cur.execute("LOCK observation_streams IN ACCESS EXCLUSIVE MODE")
    with closing(raw_connect(connect)) as conn, conn.cursor() as cur:
        cur.execute("SET ROLE fqp_observation_reader")
        with pytest.raises(psycopg2.errors.LockNotAvailable):
            cur.execute("SELECT id FROM observation_streams LIMIT 1")
    pg.rollback()


def test_history_foreign_keys_are_validated(pg):
    with pg.cursor() as cur:
        cur.execute(
            "SELECT conrelid::regclass::text,confrelid::regclass::text,convalidated "
            "FROM pg_constraint WHERE contype='f' AND conrelid=ANY("
            "ARRAY['observation_streams'::regclass,'observation_revisions'::regclass,"
            "'observation_checks'::regclass,'feature_batches'::regclass])"
        )
        rows = cur.fetchall()
    assert len(rows) == 6
    assert all(valid for _, _, valid in rows)
    assert ("observation_streams", "official_matches", True) in rows
    assert ("feature_batches", "official_matches", True) in rows
    assert ("feature_batches", "observation_cutoffs", True) in rows
