"""Opt-in migration and identity-bridge tests against an explicit disposable PG16 DB."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import errors, sql
from psycopg2.extensions import parse_dsn

from scripts.player_identity_bridge import (
    VerifiedIdentityConflict,
    resolve_player_identity,
    upsert_player_identity_link,
)

ROOT = Path(__file__).resolve().parents[2]
UP = ROOT / "sql/134_player_identity_bridge.sql"
DOWN = ROOT / "sql/down/134_player_identity_bridge.down.sql"


@pytest.fixture
def identity_database():
    dsn = os.environ.get("FQP_PLAYER_IDENTITY_TEST_DSN") or os.environ.get(
        "FQP_HISTORY_TEST_DSN", ""
    )
    if not dsn:
        pytest.skip("Explicit disposable player identity PostgreSQL database not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    dbname = params.get("dbname", "")
    assert dbname.startswith("fqp_player_identity_test_") or dbname == "fqp_history_test_ci"
    assert params.get("user") == "postgres"
    role_created = False
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "player_identity_" + uuid4().hex
        with conn.cursor() as cur:
            if dbname.startswith("fqp_player_identity_test_"):
                cur.execute(
                    "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                    "WHERE datname=current_database()"
                )
                assert cur.fetchone() == ("fqp-p108-player-identity-test/v1",)
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
            cur.execute(
                "CREATE TABLE players(id BIGINT PRIMARY KEY, player_code VARCHAR(64) UNIQUE)"
            )
            cur.execute(
                "GRANT USAGE ON SCHEMA {} TO fqp".format('"' + schema.replace('"', '""') + '"')
            )
            cur.execute((UP).read_text())
            cur.execute("GRANT SELECT ON players TO fqp")
        conn.commit()
        try:
            yield conn, schema
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute("RESET search_path")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if role_created:
                    cur.execute("DROP ROLE fqp")
            conn.commit()


def insert_player(conn, player_id, player_code=None):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO players(id,player_code) VALUES (%s,%s)", (player_id, player_code))
    conn.commit()


def link(
    conn,
    *,
    source_name="titan007",
    external_player_id="42",
    player_id=None,
    status="candidate",
    evidence="row:1",
    confidence=0.95,
    **kwargs,
):
    return upsert_player_identity_link(
        conn,
        source_name=source_name,
        external_player_id=external_player_id,
        player_id=player_id,
        status=status,
        evidence_refs=[evidence],
        matching_method="manual_review",
        confidence=confidence,
        **kwargs,
    )


def test_identity_status_revision_idempotency_and_verified_resolution(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 701)

    candidate = link(conn)
    assert candidate["revision"] == 1
    assert resolve_player_identity(conn, "titan007", "42") is None

    verified = link(
        conn,
        player_id=701,
        status="verified",
        reviewed_by="fixed-reviewer",
        reviewed_at=datetime.now(UTC),
    )
    assert verified["revision"] == 2
    assert resolve_player_identity(conn, "titan007", "42") == 701

    same = link(
        conn,
        player_id=701,
        status="verified",
        reviewed_by="fixed-reviewer",
        reviewed_at=verified["reviewed_at"],
    )
    assert same["revision"] == 2
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM player_identity_link_events WHERE source_name='titan007' AND external_player_id='42'"
        )
        assert cur.fetchone()[0] == 2


def test_high_precision_confidence_is_idempotent_after_database_rounding(identity_database):
    conn, _schema = identity_database
    first = link(conn, confidence=Decimal("0.123455"))
    repeated = link(conn, confidence=Decimal("0.123455"))

    assert first["confidence"] == Decimal("0.12346")
    assert repeated["confidence"] == Decimal("0.12346")
    assert repeated["revision"] == first["revision"] == 1
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM player_identity_link_events "
            "WHERE source_name='titan007' AND external_player_id='42'"
        )
        assert cur.fetchone()[0] == 1


def test_verified_identity_cannot_be_silently_remapped(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 701)
    insert_player(conn, 702)
    link(
        conn,
        player_id=701,
        status="verified",
        reviewed_by="reviewer",
        reviewed_at=datetime.now(UTC),
    )

    with pytest.raises(VerifiedIdentityConflict, match="verified player identity"):
        link(
            conn,
            player_id=702,
            status="verified",
            evidence="row:corrected",
            reviewed_by="reviewer",
            reviewed_at=datetime.now(UTC),
        )
    with pytest.raises(errors.RaiseException, match="verified player identity cannot be remapped"):
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE player_identity_links
                   SET player_id=702,revision=revision+1,evidence_refs='[\"row:direct\"]'::jsonb
                   WHERE source_name='titan007' AND external_player_id='42'"""
            )
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT player_id,status,revision FROM player_identity_links WHERE source_name='titan007' AND external_player_id='42'"
        )
        assert cur.fetchone() == (701, "verified", 1)


def test_audit_events_are_append_only_and_revisions_require_changed_evidence(identity_database):
    conn, _schema = identity_database
    link(conn)
    for statement in (
        "UPDATE player_identity_link_events SET status='rejected'",
        "DELETE FROM player_identity_link_events",
        "TRUNCATE player_identity_link_events",
    ):
        with pytest.raises(errors.RaiseException, match="append-only"):
            with conn.cursor() as cur:
                cur.execute(statement)
        conn.rollback()
    with pytest.raises(errors.RaiseException, match="must change mapping evidence or status"):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE player_identity_links SET revision=revision+1 WHERE source_name='titan007' AND external_player_id='42'"
            )
    conn.rollback()


def test_api_football_legacy_player_code_is_exact_fallback(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 702, "apifootball:99")

    assert resolve_player_identity(conn, "apifootball", "99") == 702
    assert resolve_player_identity(conn, "apifootball", "099") is None

    link(
        conn,
        player_id=None,
        status="candidate",
        evidence="api-import-review:99",
        source_name="apifootball",
        external_player_id="99",
    )
    assert resolve_player_identity(conn, "apifootball", "99") is None


def test_runtime_role_can_read_but_cannot_mutate_identity_links(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 701)
    link(conn)
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
        assert resolve_player_identity(conn, "titan007", "42") is None
    denied_writes = (
        "INSERT INTO player_identity_links(source_name,external_player_id,status,evidence_refs,matching_method,confidence) "
        "VALUES ('titan007','99','candidate','[\"row:99\"]','manual_review',0.5)",
        "UPDATE player_identity_links SET status='rejected' WHERE source_name='titan007' AND external_player_id='42'",
        "DELETE FROM player_identity_links WHERE source_name='titan007' AND external_player_id='42'",
        "TRUNCATE player_identity_links",
        "INSERT INTO player_identity_link_events(source_name,external_player_id,revision,status,evidence_refs,matching_method,confidence) "
        "VALUES ('titan007','42',2,'candidate','[\"row:direct\"]','manual_review',0.5)",
        "UPDATE player_identity_link_events SET status='rejected' WHERE source_name='titan007' AND external_player_id='42'",
        "DELETE FROM player_identity_link_events WHERE source_name='titan007' AND external_player_id='42'",
        "TRUNCATE player_identity_link_events",
    )
    for statement in denied_writes:
        with conn.cursor() as cur:
            cur.execute("SET ROLE fqp")
            with pytest.raises(errors.InsufficientPrivilege):
                cur.execute(statement)
        conn.rollback()


def test_external_identity_uniqueness_and_multiple_sources_per_player(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 701)
    link(
        conn,
        player_id=701,
        status="verified",
        reviewed_by="reviewer",
        reviewed_at=datetime.now(UTC),
    )
    with pytest.raises(errors.UniqueViolation):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO player_identity_links(source_name,external_player_id,status,evidence_refs,matching_method,confidence) VALUES ('titan007','42','candidate','[\"row:duplicate\"]','manual_review',0.5)"
            )
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO player_identity_links(source_name,external_player_id,player_id,status,evidence_refs,matching_method,confidence,reviewed_by,reviewed_at) VALUES ('other_source','42',701,'verified','[\"other:42\"]','authoritative_crosswalk',1,'reviewer',now())"
        )
        cur.execute(
            "SELECT count(*) FROM player_identity_links WHERE player_id=701 AND status='verified'"
        )
        assert cur.fetchone()[0] == 2


def test_down_migration_refuses_existing_identity_data(identity_database):
    conn, _schema = identity_database
    insert_player(conn, 701)
    link(conn)
    with conn.cursor() as cur:
        with pytest.raises(errors.RaiseException, match="identity mappings exist"):
            cur.execute((DOWN).read_text())
        conn.rollback()
        cur.execute("SELECT count(*) FROM player_identity_links")
        assert cur.fetchone()[0] == 1


def test_concurrent_first_upserts_create_one_mapping_and_one_event(identity_database):
    conn, schema = identity_database
    barrier = Barrier(2)
    dsn = os.environ.get("FQP_PLAYER_IDENTITY_TEST_DSN") or os.environ["FQP_HISTORY_TEST_DSN"]

    class BarrierCursor:
        def __init__(self, cursor):
            self.cursor = cursor
            self.query = ""

        def execute(self, query, params=None):
            self.query = str(query)
            self.cursor.execute(query, params)

        def fetchone(self):
            row = self.cursor.fetchone()
            if (
                row is None
                and self.query.lstrip().startswith("SELECT")
                and "player_identity_links" in self.query
            ):
                barrier.wait(timeout=10)
            return row

        def __enter__(self):
            self.cursor.__enter__()
            return self

        def __exit__(self, *args):
            return self.cursor.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class BarrierConnection:
        def __init__(self, connection):
            self.connection = connection

        def cursor(self):
            return BarrierCursor(self.connection.cursor())

        def __getattr__(self, name):
            return getattr(self.connection, name)

    def concurrent_upsert(_index):
        local = psycopg2.connect(dsn, options=f"-c search_path={schema}")
        with closing(local):
            return upsert_player_identity_link(
                BarrierConnection(local),
                source_name="titan007",
                external_player_id="parallel-42",
                player_id=None,
                status="candidate",
                evidence_refs=["row:parallel-42"],
                matching_method="manual_review",
                confidence=0.5,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(concurrent_upsert, range(2)))

    assert [result["revision"] for result in results] == [1, 1]
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM player_identity_links "
            "WHERE source_name='titan007' AND external_player_id='parallel-42'"
        )
        assert cur.fetchone()[0] == 1
        cur.execute(
            "SELECT count(*) FROM player_identity_link_events "
            "WHERE source_name='titan007' AND external_player_id='parallel-42'"
        )
        assert cur.fetchone()[0] == 1


def test_empty_schema_can_down_and_reapply_migration(identity_database):
    conn, _schema = identity_database
    with conn.cursor() as cur:
        cur.execute((DOWN).read_text())
        cur.execute((UP).read_text())
        cur.execute("SELECT to_regclass('player_identity_links')")
        assert cur.fetchone()[0] is not None
    conn.rollback()
