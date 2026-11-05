"""PostgreSQL regressions for bounded dashboard prediction rollups."""

from __future__ import annotations

import os
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from ops.server.migrate import _sql_statements
from scripts import prediction_statistics as statistics


def test_default_refresh_batch_stays_within_hdd_budget():
    # Production timed out the 500-match rollup query at its 120-second limit.
    assert statistics.DEFAULT_REFRESH_BATCH_SIZE <= 25


@pytest.fixture
def statistics_database(request):
    dsn = os.getenv("FQP_P106_TEST_DATABASE_URL") or os.getenv("FQP_AUDIT_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set an isolated local PostgreSQL test database URL")
    parsed = urlparse(dsn)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("prediction statistics tests only accept a loopback database host")
    database_name = parsed.path.lstrip("/")
    if not database_name.startswith(("fqp_p106_test_", "fqp_audit_test_")):
        pytest.fail("prediction statistics tests require a dedicated *_test database")

    schema = f"prediction_statistics_{uuid4().hex}"
    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    role_created = False
    with connection.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname='fqp'")
        if cur.fetchone() is None:
            cur.execute("CREATE ROLE fqp NOLOGIN")
            role_created = True
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            """CREATE TABLE model_versions (
                id BIGINT PRIMARY KEY, model_name VARCHAR(128) NOT NULL
            )"""
        )
        cur.execute(
            """CREATE TABLE official_matches (
                id BIGINT PRIMARY KEY, kickoff_time TIMESTAMP NOT NULL
            )"""
        )
        cur.execute(
            """CREATE TABLE model_predictions (
                id BIGINT PRIMARY KEY,
                match_id BIGINT NOT NULL,
                model_version_id BIGINT NOT NULL,
                predict_time TIMESTAMP NOT NULL,
                play_type VARCHAR(32) NOT NULL,
                option_code VARCHAR(64) NOT NULL,
                ev NUMERIC(10,6),
                confidence_score NUMERIC(10,4),
                validation_status VARCHAR(32),
                uncertainty_reason JSONB
            )"""
        )
        cur.execute(
            """CREATE INDEX idx_predictions_validation_latest
                ON model_predictions (
                    validation_status, match_id, model_version_id, play_type,
                    option_code, predict_time DESC, id DESC
                )"""
        )
        cur.execute(
            """CREATE INDEX idx_predictions_identity_latest
                ON model_predictions (
                    match_id, model_version_id, play_type, option_code,
                    predict_time DESC, id DESC
                )"""
        )
        cur.execute(
            """CREATE TABLE model_prediction_runs (
                id UUID PRIMARY KEY, run_status VARCHAR(32) NOT NULL
            )"""
        )
        cur.execute(
            """CREATE TABLE model_prediction_groups (
                id UUID PRIMARY KEY,
                run_id UUID NOT NULL REFERENCES model_prediction_runs(id),
                match_id BIGINT NOT NULL,
                model_version_id BIGINT NOT NULL,
                play_type VARCHAR(32) NOT NULL,
                group_status VARCHAR(16) NOT NULL,
                predict_time TIMESTAMP NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )"""
        )
        cur.execute(
            """CREATE TABLE model_prediction_group_options (
                group_id UUID NOT NULL REFERENCES model_prediction_groups(id),
                option_code VARCHAR(64) NOT NULL,
                prediction_id BIGINT NOT NULL UNIQUE REFERENCES model_predictions(id),
                PRIMARY KEY (group_id, option_code)
            )"""
        )
        cur.execute(
            """CREATE TABLE ai_job_runs (
                id BIGSERIAL PRIMARY KEY,
                job_code VARCHAR(128) NOT NULL,
                job_name VARCHAR(128) NOT NULL,
                owner_agent VARCHAR(128) NOT NULL,
                schedule_type VARCHAR(64),
                environment VARCHAR(32),
                input_snapshot_refs JSONB,
                output_refs JSONB,
                status VARCHAR(32) NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                duration_ms BIGINT,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )
        cur.execute("CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY)")
        cur.execute(
            """GRANT SELECT, INSERT, UPDATE, DELETE ON
                   model_versions, official_matches, model_predictions,
                   model_prediction_runs, model_prediction_groups,
                   model_prediction_group_options TO fqp"""
        )

    migration = Path(__file__).resolve().parents[2] / "sql/131_prediction_statistics_rollup.sql"
    with connection.cursor() as cur:
        cur.execute(migration.read_text(encoding="utf-8"))
        cur.execute(
            """SELECT
                   has_table_privilege('fqp', %s, 'SELECT'),
                   has_table_privilege('fqp', %s, 'INSERT'),
                   has_table_privilege('fqp', %s, 'UPDATE'),
                   has_table_privilege('fqp', %s, 'DELETE')""",
            (
                f"{schema}.prediction_statistics_dirty_matches",
                f"{schema}.prediction_statistics_dirty_matches",
                f"{schema}.prediction_statistics_match_rollups",
                f"{schema}.prediction_statistics_match_rollups",
            ),
        )
        assert cur.fetchone() == (True, True, True, True)
    connection.autocommit = False

    def connect():
        runtime = psycopg2.connect(dsn)
        with runtime.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        runtime.commit()
        return runtime

    def cleanup() -> None:
        try:
            if not connection.closed:
                connection.rollback()
                connection.autocommit = True
                with connection.cursor() as cur:
                    cur.execute("SET search_path TO public")
                    cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
                if role_created:
                    with connection.cursor() as cur:
                        cur.execute("DROP ROLE fqp")
        finally:
            connection.close()

    request.addfinalizer(cleanup)
    yield connection, connect


def _insert_match_and_legacy_predictions(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO model_versions(id, model_name) VALUES (1,'maher_poisson'),(2,'maher_poisson'),(3,'elo_rating')"
        )
        cur.execute(
            "INSERT INTO official_matches(id, kickoff_time) VALUES "
            "(101,'2026-11-03 20:00'),(102,'2026-11-03 20:00'),(103,'2026-11-03 20:00')"
        )
        cur.execute(
            """INSERT INTO model_predictions
                   (id,match_id,model_version_id,predict_time,play_type,option_code,
                    ev,confidence_score,validation_status,uncertainty_reason)
               VALUES
                   (1001,101,1,'2026-11-03 19:00','spf','3',0.1,0.6,'valid','{"model_independent":true}'),
                   (1002,101,1,'2026-11-03 19:00','spf','1',-0.1,0.4,'valid','{"model_independent":true}'),
                   (1003,101,1,'2026-11-03 19:00','spf','0',0.0,0.3,'valid','{"model_independent":true}'),
                   (1004,101,2,'2026-11-03 19:30','spf','3',0.2,0.8,'valid','{"model_independent":true}'),
                   (1005,101,2,'2026-11-03 19:30','spf','1',0.1,0.7,'valid','{"model_independent":true}'),
                   (1006,101,2,'2026-11-03 19:30','spf','0',-0.2,0.5,'valid','{"model_independent":true}'),
                   (1007,101,3,'2026-11-03 19:10','rqspf','3',0.1,0.9,'valid','{"model_independent":true}'),
                   (1008,101,3,'2026-11-03 19:10','rqspf','1',0.0,0.8,'valid','{"model_independent":true}'),
                   (1009,101,3,'2026-11-03 19:10','rqspf','0',-0.1,0.7,'valid','{"model_independent":true}'),
                   (1010,102,1,'2026-11-03 19:00','spf','3',0.4,0.5,'valid','{"model_independent":true}'),
                   (1011,102,1,'2026-11-03 20:00','spf','1',0.2,0.4,'valid','{"model_independent":true}'),
                   (1012,102,1,'2026-11-03 19:00','spf','0',0.3,0.3,'rejected','{"model_independent":true}')"""
        )
        cur.execute("ANALYZE model_predictions")


def _refresh(conn, batch_size: int = 500):
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (913201, 114))
        assert cur.fetchone() == (True,)
    result = statistics._refresh_prediction_statistics_batch(conn, batch_size=batch_size)
    conn.commit()
    return result


def test_rollup_batches_match_full_scan_reference_and_publish_only_when_drained(
    statistics_database,
):
    conn, _ = statistics_database
    _insert_match_and_legacy_predictions(conn)

    first = _refresh(conn, batch_size=2)
    assert first == {"status": "partial", "matches_refreshed": 2, "pending_matches": 1}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_match_rollups")
        assert cur.fetchone()[0] == 2

    second = _refresh(conn, batch_size=2)
    assert second["status"] == "completed"
    assert second["matches_refreshed"] == 1
    reference = statistics.compute_prediction_snapshots(conn)
    assert (
        second["snapshots"]["prediction_count"]["total"] == reference["prediction_count"]["total"]
    )
    actual = second["snapshots"]["prediction_summary"]
    expected = reference["prediction_summary"]
    assert actual["total"] == expected["total"] == 7
    assert actual["positive_ev_count"] == expected["positive_ev_count"]
    assert actual["avg_confidence"] == pytest.approx(expected["avg_confidence"])
    assert actual["model_count"] == expected["model_count"] == 2
    assert actual["latest_predict_time"] == expected["latest_predict_time"]

    # A source update after its row was claimed must leave a new invalidation.
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO model_predictions VALUES "
            "(1013,103,1,'2026-11-03 19:15','spf','3',0.8,0.9,'valid','{\"model_independent\":true}')"
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_dirty_matches WHERE match_id=103")
        assert cur.fetchone()[0] == 1
    refreshed = _refresh(conn, batch_size=1)
    assert refreshed["status"] == "completed"
    assert (
        refreshed["snapshots"]["prediction_count"]["total"]
        == statistics.compute_prediction_count(conn)["total"]
    )


def test_rollback_restores_claim_and_update_delete_and_kickoff_changes_invalidate(
    statistics_database,
):
    conn, _ = statistics_database
    _insert_match_and_legacy_predictions(conn)
    conn.commit()
    first = statistics._refresh_prediction_statistics_batch(conn, batch_size=1)
    assert first["status"] == "partial"
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_dirty_matches")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_match_rollups")
        assert cur.fetchone()[0] == 0

    # Finish the initial bounded backfill.
    assert _refresh(conn, batch_size=3)["status"] == "completed"
    with conn.cursor() as cur:
        cur.execute("UPDATE model_predictions SET validation_status='rejected' WHERE id=1001")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("UPDATE official_matches SET kickoff_time='2026-11-03 18:30' WHERE id=102")
        cur.execute("DELETE FROM model_predictions WHERE id=1010")
        cur.execute("SELECT COUNT(DISTINCT match_id) FROM prediction_statistics_dirty_matches")
        assert cur.fetchone()[0] == 2
    conn.commit()
    refreshed = _refresh(conn, batch_size=2)
    reference = statistics.compute_prediction_snapshots(conn)
    assert refreshed["status"] == "completed"
    assert (
        refreshed["snapshots"]["prediction_count"]["total"]
        == reference["prediction_count"]["total"]
    )
    assert (
        refreshed["snapshots"]["prediction_summary"]["total"]
        == reference["prediction_summary"]["total"]
    )


def test_writer_waiting_on_claimed_match_is_requeued_after_batch_commit(statistics_database):
    conn, connect = statistics_database
    _insert_match_and_legacy_predictions(conn)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("UPDATE prediction_statistics_dirty_matches SET changed_at='2026-01-01'")
        cur.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (913201, 114))
        assert cur.fetchone() == (True,)
    first = statistics._refresh_prediction_statistics_batch(conn, batch_size=1)
    assert first["status"] == "partial"
    assert first["matches_refreshed"] == 1

    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def update_claimed_match():
        writer = connect()
        try:
            started.set()
            with writer.cursor() as cur:
                cur.execute(
                    "UPDATE model_predictions SET validation_status='rejected' WHERE id=1001"
                )
            writer.commit()
        except BaseException as exc:  # propagate background database errors to pytest
            errors.append(exc)
        finally:
            finished.set()
            writer.close()

    writer_thread = threading.Thread(target=update_claimed_match)
    writer_thread.start()
    assert started.wait(5)
    time.sleep(0.1)
    assert not finished.is_set(), "the source writer should wait for the claimed queue row"

    # Committing the batch releases its deleted queue row. The blocked trigger
    # then inserts a fresh invalidation for the source change.
    conn.commit()
    assert finished.wait(5)
    writer_thread.join(timeout=5)
    assert not errors
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_dirty_matches WHERE match_id=101")
        assert cur.fetchone()[0] == 1

    final = _refresh(conn)
    assert final["status"] == "completed"
    assert (
        final["snapshots"]["prediction_count"]["total"]
        == statistics.compute_prediction_count(conn)["total"]
    )


def test_run_group_option_and_model_identity_changes_invalidate_matches(statistics_database):
    conn, _ = statistics_database
    _insert_match_and_legacy_predictions(conn)
    assert _refresh(conn, batch_size=3)["status"] == "completed"
    run_id = uuid4()
    group_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO model_prediction_runs(id,run_status) VALUES (%s,'running')",
            (str(run_id),),
        )
        cur.execute(
            """INSERT INTO model_prediction_groups
                   (id,run_id,match_id,model_version_id,play_type,group_status,predict_time)
               VALUES (%s,%s,101,2,'spf','building','2026-11-03 19:30')""",
            (str(group_id), str(run_id)),
        )
        cur.execute(
            "INSERT INTO model_prediction_group_options(group_id,option_code,prediction_id) "
            "VALUES (%s,'3',1004)",
            (str(group_id),),
        )
        cur.execute(
            "UPDATE model_prediction_groups SET group_status='complete' WHERE id=%s",
            (str(group_id),),
        )
        cur.execute(
            "UPDATE model_prediction_runs SET run_status='completed' WHERE id=%s",
            (str(run_id),),
        )
        cur.execute("UPDATE model_versions SET model_name='maher_revised' WHERE id=2")
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches ORDER BY match_id")
        assert cur.fetchall() == [(101,)]
    conn.commit()
    refreshed = _refresh(conn, batch_size=1)
    assert refreshed["status"] == "completed"
    reference = statistics.compute_prediction_snapshots(conn)
    assert (
        refreshed["snapshots"]["prediction_count"]["total"]
        == reference["prediction_count"]["total"]
    )
    assert (
        refreshed["snapshots"]["prediction_summary"]["total"]
        == reference["prediction_summary"]["total"]
    )
    assert refreshed["snapshots"]["prediction_summary"]["model_count"] == 3


def test_option_update_delete_group_delete_and_match_lifecycle_invalidate_rollups(
    statistics_database,
):
    conn, _ = statistics_database
    _insert_match_and_legacy_predictions(conn)
    assert _refresh(conn, batch_size=3)["status"] == "completed"

    run_id = uuid4()
    group_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO model_prediction_runs(id,run_status) VALUES (%s,'running')",
            (str(run_id),),
        )
        cur.execute(
            """INSERT INTO model_prediction_groups
                   (id,run_id,match_id,model_version_id,play_type,group_status,predict_time)
               VALUES (%s,%s,101,2,'spf','building','2026-11-03 19:30')""",
            (str(group_id), str(run_id)),
        )
        cur.execute(
            "INSERT INTO model_prediction_group_options(group_id,option_code,prediction_id) "
            "VALUES (%s,'3',1004)",
            (str(group_id),),
        )
        cur.execute(
            "UPDATE model_prediction_group_options SET prediction_id=1001 "
            "WHERE group_id=%s AND option_code='3'",
            (str(group_id),),
        )
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches")
        assert cur.fetchall() == [(101,)]
    assert _refresh(conn, batch_size=1)["status"] == "completed"

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM model_prediction_group_options WHERE group_id=%s AND option_code='3'",
            (str(group_id),),
        )
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches")
        assert cur.fetchall() == [(101,)]
    assert _refresh(conn, batch_size=1)["status"] == "completed"

    with conn.cursor() as cur:
        cur.execute("DELETE FROM model_prediction_groups WHERE id=%s", (str(group_id),))
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches")
        assert cur.fetchall() == [(101,)]
    assert _refresh(conn, batch_size=1)["status"] == "completed"

    with conn.cursor() as cur:
        cur.execute("INSERT INTO official_matches(id,kickoff_time) VALUES (104,'2026-11-03 20:00')")
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches")
        assert cur.fetchall() == [(104,)]
    assert _refresh(conn, batch_size=1)["status"] == "completed"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT raw_prediction_total FROM prediction_statistics_match_rollups "
            "WHERE match_id=104"
        )
        assert cur.fetchone() == (0,)

    with conn.cursor() as cur:
        cur.execute("DELETE FROM official_matches WHERE id=104")
        cur.execute("SELECT match_id FROM prediction_statistics_dirty_matches")
        assert cur.fetchall() == [(104,)]
    assert _refresh(conn, batch_size=1)["status"] == "completed"
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_match_rollups WHERE match_id=104")
        assert cur.fetchone()[0] == 0


def test_down_migration_declares_an_atomic_transaction():
    migration = (
        Path(__file__).resolve().parents[2] / "sql/down/131_prediction_statistics_rollup.down.sql"
    ).read_text(encoding="utf-8")
    normalized = migration.strip().upper()
    assert normalized.startswith("BEGIN;")
    assert normalized.endswith("COMMIT;")


def test_down_migration_failure_rolls_back_earlier_drops(statistics_database):
    conn, _ = statistics_database
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO local_schema_migrations(filename) "
            "VALUES ('131_prediction_statistics_rollup.sql')"
        )
        cur.execute(
            "CREATE VIEW block_prediction_statistics_drop AS "
            "SELECT match_id FROM prediction_statistics_match_rollups"
        )
    conn.commit()

    migration = (
        Path(__file__).resolve().parents[2] / "sql/down/131_prediction_statistics_rollup.down.sql"
    ).read_text(encoding="utf-8")
    statements = [migration[start:end].strip() for start, end, _, _ in _sql_statements(migration)]
    conn.autocommit = True
    with pytest.raises(psycopg2.errors.DependentObjectsStillExist):
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
    with conn.cursor() as cur:
        cur.execute("ROLLBACK")
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM pg_trigger trigger "
            "JOIN pg_class relation ON relation.oid=trigger.tgrelid "
            "JOIN pg_namespace namespace ON namespace.oid=relation.relnamespace "
            "WHERE namespace.nspname=current_schema() "
            "AND trigger.tgname='trg_prediction_statistics_prediction_insert' "
            "AND NOT trigger.tgisinternal"
        )
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT to_regclass('prediction_statistics_match_rollups')")
        assert cur.fetchone()[0] is not None
        cur.execute(
            "SELECT COUNT(*) FROM local_schema_migrations "
            "WHERE filename='131_prediction_statistics_rollup.sql'"
        )
        assert cur.fetchone()[0] == 1
        cur.execute("DROP VIEW block_prediction_statistics_drop")
    conn.commit()


def test_two_match_refresh_does_not_scan_unrelated_prediction_history(statistics_database):
    conn, _ = statistics_database
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(id,model_name) VALUES (1,'maher_poisson')")
        cur.execute(
            "INSERT INTO official_matches(id,kickoff_time) "
            "SELECT id,'2026-11-03 20:00'::timestamp FROM generate_series(1,500) id"
        )
        cur.execute(
            """INSERT INTO model_predictions
                   (id,match_id,model_version_id,predict_time,play_type,option_code,
                    ev,confidence_score,validation_status,uncertainty_reason)
               SELECT seq, ((seq - 1) / 100) + 1, 1, '2026-11-03 19:00', 'spf',
                      CASE seq % 3 WHEN 0 THEN '3' WHEN 1 THEN '1' ELSE '0' END,
                      0.1, 0.5, 'valid', '{"model_independent":true}'::jsonb
               FROM generate_series(1,50000) seq"""
        )
        cur.execute("ANALYZE model_predictions")
        cur.execute("ANALYZE official_matches")
        cur.execute("DELETE FROM prediction_statistics_dirty_matches")
        cur.execute(
            "CREATE TEMP TABLE prediction_statistics_refresh_targets "
            "(match_id BIGINT PRIMARY KEY) ON COMMIT DROP"
        )
        cur.execute("INSERT INTO prediction_statistics_refresh_targets VALUES (1),(500)")
        cur.execute(
            "EXPLAIN (ANALYZE, FORMAT JSON) " + statistics._REFRESH_PREDICTION_STATISTICS_SQL
        )
        plan = cur.fetchone()[0][0]

    def examined_prediction_rows(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node.get("Actual Rows", 0) + node.get("Rows Removed by Filter", 0)) * node.get(
                "Actual Loops", 1
            )
        return own + sum(examined_prediction_rows(child) for child in node.get("Plans", []))

    examined = examined_prediction_rows(plan["Plan"])

    def prediction_scan_nodes(node, parent=None):
        entries = []
        if node.get("Relation Name") == "model_predictions":
            entries.append(
                {
                    "parent": parent,
                    "type": node.get("Node Type"),
                    "index": node.get("Index Name"),
                    "rows": node.get("Actual Rows"),
                    "loops": node.get("Actual Loops"),
                }
            )
        for child in node.get("Plans", []):
            entries.extend(prediction_scan_nodes(child, node.get("Node Type")))
        return entries

    print(
        {
            "archive_prediction_rows": 50000,
            "target_matches": 2,
            "prediction_rows_examined": examined,
            "model_prediction_nodes": prediction_scan_nodes(plan["Plan"]),
            "execution_time_ms": plan["Execution Time"],
        },
        flush=True,
    )
    assert examined < 2000, "refreshing two matches must not read unrelated prediction history"


def test_down_migration_preserves_source_rows_and_up_migration_reseeds_queue(
    statistics_database,
):
    conn, _ = statistics_database
    _insert_match_and_legacy_predictions(conn)
    conn.commit()
    migrations = Path(__file__).resolve().parents[2] / "sql"
    conn.autocommit = True
    with conn.cursor() as cur:
        migration_down = (migrations / "down/131_prediction_statistics_rollup.down.sql").read_text(
            encoding="utf-8"
        )
        assert migration_down.strip().upper().startswith("BEGIN;")
        assert migration_down.strip().upper().endswith("COMMIT;")
        cur.execute(
            "INSERT INTO local_schema_migrations(filename) "
            "VALUES ('131_prediction_statistics_rollup.sql')"
        )
        cur.execute(migration_down)
        cur.execute(
            "SELECT COUNT(*) FROM local_schema_migrations "
            "WHERE filename='131_prediction_statistics_rollup.sql'"
        )
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM model_predictions")
        assert cur.fetchone()[0] == 12
        cur.execute("SELECT to_regclass('prediction_statistics_match_rollups')")
        assert cur.fetchone()[0] is None
        cur.execute((migrations / "131_prediction_statistics_rollup.sql").read_text())
        cur.execute("SELECT COUNT(*) FROM prediction_statistics_dirty_matches")
        assert cur.fetchone()[0] == 3
    conn.autocommit = False
    result = _refresh(conn, batch_size=3)
    assert result["status"] == "completed"
    assert result["snapshots"]["prediction_count"]["total"] == 10


def test_runtime_role_can_fire_triggers_and_refresh_with_granted_access(statistics_database):
    _, connect = statistics_database
    conn = connect()
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
        cur.execute("INSERT INTO model_versions(id,model_name) VALUES (1,'maher_poisson')")
        cur.execute("INSERT INTO official_matches(id,kickoff_time) VALUES (1,'2026-11-03 20:00')")
        cur.execute(
            """INSERT INTO model_predictions
                   (id,match_id,model_version_id,predict_time,play_type,option_code,
                    ev,confidence_score,validation_status,uncertainty_reason)
               VALUES (1,1,1,'2026-11-03 19:00','spf','3',0.2,0.7,'valid',
                       '{"model_independent":true}')"""
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s,%s)", (913201, 114))
        assert cur.fetchone() == (True,)
    refreshed = statistics._refresh_prediction_statistics_batch(conn, batch_size=10)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("RESET ROLE")
    assert refreshed["status"] == "completed"
    assert refreshed["snapshots"]["prediction_count"]["total"] == 1
    conn.close()


def test_audited_refresh_preserves_last_complete_snapshot_during_backfill(
    statistics_database, monkeypatch
):
    conn, connect = statistics_database
    _insert_match_and_legacy_predictions(conn)
    conn.commit()

    @contextmanager
    def test_connection():
        connection = connect()
        try:
            yield connection
        finally:
            connection.close()

    monkeypatch.setattr(statistics, "get_db", test_connection)
    first = statistics.refresh_prediction_count(batch_size=2)
    assert first == {
        "status": "refreshing",
        "refreshing": True,
        "matches_refreshed": 2,
        "pending_matches": 1,
    }
    with closing(connect()) as reader:
        assert statistics.get_prediction_count_snapshot(reader)["status"] == "pending"
        assert statistics.get_prediction_summary_snapshot(reader)["meta"]["status"] == "pending"

    second = statistics.refresh_prediction_count(batch_size=2)
    assert second["status"] == "ok"
    with closing(connect()) as reader:
        previous_count = statistics.get_prediction_count_snapshot(reader)
        previous_summary = statistics.get_prediction_summary_snapshot(reader)
        assert previous_count["total"] == 10
        assert previous_count["status"] == "ok"
        assert previous_summary["summary"]["total"] == 7

    with conn.cursor() as cur:
        cur.execute("UPDATE model_predictions SET validation_status='rejected' WHERE id=1001")
        cur.execute("UPDATE official_matches SET kickoff_time='2026-11-03 18:30' WHERE id=102")
    conn.commit()

    third = statistics.refresh_prediction_count(batch_size=1)
    assert third["status"] == "refreshing"
    with closing(connect()) as reader:
        during_refresh = statistics.get_prediction_count_snapshot(reader)
        summary_during_refresh = statistics.get_prediction_summary_snapshot(reader)
        assert during_refresh["total"] == previous_count["total"]
        assert during_refresh["status"] == "stale"
        assert summary_during_refresh["summary"]["total"] == previous_summary["summary"]["total"]
        assert summary_during_refresh["meta"]["status"] == "stale"
        assert summary_during_refresh["meta"]["is_stale"] is True

    fourth = statistics.refresh_prediction_count(batch_size=1)
    assert fourth["status"] == "ok"
    with closing(connect()) as reader:
        current = statistics.get_prediction_count_snapshot(reader)
        assert current["total"] == 8
        assert current["status"] == "ok"
        with reader.cursor() as cur:
            cur.execute("SELECT status FROM ai_job_runs ORDER BY id")
            assert cur.fetchall() == [
                ("partial",),
                ("completed",),
                ("partial",),
                ("completed",),
            ]
