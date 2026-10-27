"""Ownership/recovery against disposable PostgreSQL; no provider/production access."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from contextlib import closing, contextmanager
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import Json

from scripts import prediction_job_execution as ownership
from scripts.model_prediction_run_storage import (
    create_prediction_run,
    finalize_prediction_run,
    store_prediction_group,
)
from tests.test_computation.test_prediction_run_postgres import (
    isolated_database as isolated_database,
)


class ClosingPool:
    def __init__(self, connection):
        self.connection = connection
        self.returned = []

    def getconn(self):
        return self.connection()

    def putconn(self, conn, *, close):
        assert close is True
        conn.close()
        self.returned.append(conn)


@pytest.fixture
def database(isolated_database, monkeypatch):
    conn, schema = isolated_database
    with conn.cursor() as cur:
        cur.execute("""ALTER TABLE ai_job_runs
            ADD COLUMN job_code VARCHAR(128) NOT NULL,
            ADD COLUMN job_name VARCHAR(128) NOT NULL,
            ADD COLUMN owner_agent VARCHAR(128) NOT NULL,
            ADD COLUMN schedule_type TEXT, ADD COLUMN environment TEXT,
            ADD COLUMN input_snapshot_refs JSONB, ADD COLUMN output_refs JSONB,
            ADD COLUMN status TEXT, ADD COLUMN started_at TIMESTAMP,
            ADD COLUMN finished_at TIMESTAMP, ADD COLUMN duration_ms INTEGER,
            ADD COLUMN error_message TEXT, ADD COLUMN created_at TIMESTAMP DEFAULT now()""")
        cur.execute("INSERT INTO official_matches DEFAULT VALUES")
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('fixture')")
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            "GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA "
            + sql.Identifier(schema).as_string(conn)
            + " TO fqp"
        )
        cur.execute(
            "GRANT USAGE ON ALL SEQUENCES IN SCHEMA "
            + sql.Identifier(schema).as_string(conn)
            + " TO fqp"
        )
    conn.commit()

    def connection():
        fresh = psycopg2.connect(
            os.environ["FQP_P106_TEST_DATABASE_URL"],
            options="-c statement_timeout=5000 -c lock_timeout=1000",
        )
        with fresh.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("SET ROLE fqp")
        fresh.commit()
        return fresh

    pool = ClosingPool(connection)
    monkeypatch.setattr(ownership, "get_pool", lambda: pool)
    yield conn, connection, pool, schema
    assert all(c.closed for c in pool.returned)


def seed(conn, *, managed=True, parent="running", child=True):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ai_job_runs(job_code, job_name, owner_agent, input_snapshot_refs, status,
                       started_at, error_message)
                       VALUES ('model_prediction', 'model_prediction', 'model_agent',
                               %s, %s, now()-interval '30 days', %s)
                       RETURNING id""",
            (
                Json({"execution_protocol": ownership.EXECUTION_PROTOCOL} if managed else {}),
                parent,
                "original recorded failure" if parent == "failed" else None,
            ),
        )
        job_id = cur.fetchone()[0]
    conn.commit()
    run_id = uuid4() if child else None
    if child:
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=job_id,
            release_id="fixture",
            code_fingerprint={"sha256": "a" * 64},
            model_manifest=[],
            input_manifest={},
            provenance_status="incomplete",
        )
    return job_id, run_id


def publish(conn, run_id):
    metadata = {
        "match_id": 1,
        "model_version_id": 1,
        "play_type": "spf",
        "predict_time": "2026-10-24T10:00:00",
        "expected_options": ["3", "1", "0"],
        "odds_snapshot_ids": {"3": 30, "1": 31, "0": 32},
        "feature_snapshot_id": 77,
    }
    rows = [
        dict(
            metadata,
            option_code=option,
            model_probability=probability,
            odds_snapshot_id=metadata["odds_snapshot_ids"][option],
            market_probability=probability,
            break_even_probability=probability,
            market_edge=0.0,
            breakeven_edge=0.0,
            ev=0.0,
            validation_status="valid",
            calculation_version="fixture-v1",
        )
        for option, probability in [("3", 0.5), ("1", 0.25), ("0", 0.25)]
    ]
    return store_prediction_group(conn, run_id=run_id, metadata=metadata, predictions=rows)


def states(conn):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("""SELECT j.id,j.status,r.run_status,r.output_summary
                       FROM ai_job_runs j LEFT JOIN model_prediction_runs r
                         ON r.ai_job_run_id=j.id ORDER BY j.id""")
        return cur.fetchall()


def test_live_long_owner_survives_contender_commit_and_rollback(database):
    conn, connection, pool, _ = database
    with ownership.prediction_execution() as owner:
        job_id, run_id = seed(owner)
        for end in (owner.commit, owner.rollback):
            end()
            # Keep no idle transaction on the ownership session between writes.
            # Runtime-role sessions intentionally cannot inspect other owners'
            # pg_stat_activity details. Use the fixture admin only to observe.
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state FROM pg_stat_activity WHERE pid=%s", (owner.get_backend_pid(),)
                )
                assert cur.fetchone()[0] == "idle"
            conn.rollback()
            with ownership.prediction_execution() as contender:
                assert contender is None
            assert states(conn)[0][:3] == (job_id, "running", "running")
        publish(owner, run_id)
    assert owner.closed and len(pool.returned) == 3
    with ownership.prediction_execution():
        pass
    assert states(conn)[0][1:3] == ("failed", "failed")


@pytest.mark.parametrize("parent", ["running", "failed"])
def test_recovery_preserves_published_outputs_unknown_counts_and_original_error(database, parent):
    conn, _, _, _ = database
    job_id, run_id = seed(conn, parent=parent)
    group_id = publish(conn, run_id)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT output_sha256,output_manifest_canonical FROM model_prediction_groups WHERE id=%s",
            (str(group_id),),
        )
        group_before = cur.fetchone()
    with ownership.prediction_execution():
        pass
    [(saved_job, job_status, run_status, summary)] = states(conn)
    assert (saved_job, job_status, run_status) == (job_id, "failed", "failed")
    with conn.cursor() as cur:
        cur.execute("SELECT duration_ms FROM ai_job_runs WHERE id=%s", (job_id,))
        # Real schema13 uses INT milliseconds: 30 days cannot fit. Preserve
        # exact start/finish timestamps, leave duration unknown instead of
        # overflowing the recovery transaction or reporting a capped duration.
        assert cur.fetchone()[0] is None
    assert summary["completed_groups"] == 1 and summary["counts_complete"] is False
    assert summary["expected_groups"] is None and summary["skipped_groups"] is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT output_sha256,output_manifest_canonical FROM model_prediction_groups WHERE id=%s",
            (str(group_id),),
        )
        assert cur.fetchone() == group_before
        cur.execute("SELECT count(*) FROM model_predictions")
        assert cur.fetchone()[0] == 3
        cur.execute(
            "SELECT output_manifest_sha256,output_manifest_canonical,error_message FROM model_prediction_runs WHERE id=%s",
            (str(run_id),),
        )
        digest, canonical, error = cur.fetchone()
        assert hashlib.sha256(bytes(canonical)).hexdigest() == digest
        if parent == "failed":
            assert "original recorded failure" in error
        cur.execute("SELECT error_message FROM ai_job_runs WHERE id=%s", (job_id,))
        if parent == "failed":
            assert cur.fetchone()[0] == "original recorded failure"
    # Recovery is idempotent and terminal manifests remain unchanged.
    before = states(conn)
    with ownership.prediction_execution():
        pass
    assert states(conn) == before


@pytest.mark.parametrize("terminal", ["completed", "partial"])
def test_finalized_output_is_not_reclassified_failed_for_missing_audit_ack(database, terminal):
    conn, _, _, _ = database
    _, run_id = seed(conn)
    finalize_prediction_run(
        conn,
        run_id=run_id,
        run_status=terminal,
        output_summary={
            "expected_groups": int(terminal == "partial"),
            "completed_groups": 0,
            "skipped_groups": int(terminal == "partial"),
            "missing_groups": [{"reason": "missing_input"}] if terminal == "partial" else [],
            "input_updates_skipped": 0,
            "completion_reason": "fixture",
        },
    )
    with ownership.prediction_execution():
        pass
    assert states(conn)[0][1:3] == ("ok", terminal)


def test_legacy_history_and_unlinked_business_runs_are_left_unchanged(database):
    conn, _, _, _ = database
    seed(conn, managed=False)
    seed(conn, managed=False, parent="failed")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO backtest_runs(name,status) VALUES ('unlinked','running')")
    conn.commit()
    before = states(conn)
    with ownership.prediction_execution():
        pass
    assert states(conn) == before
    with conn.cursor() as cur:
        cur.execute("SELECT status FROM backtest_runs")
        assert cur.fetchone() == ("running",)


@pytest.mark.parametrize("failure", ["job_update", "commit"])
def test_recovery_failure_rolls_back_child_manifest_and_job_together(database, failure):
    conn, _, _, _ = database
    _, run_id = seed(conn)
    publish(conn, run_id)
    seed(conn)
    before = states(conn)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION stop_recovery() RETURNS trigger LANGUAGE plpgsql AS $$
                       BEGIN RAISE EXCEPTION 'injected recovery failure'; END; $$""")
        if failure == "job_update":
            cur.execute(
                "CREATE TRIGGER stop_recovery BEFORE UPDATE ON ai_job_runs FOR EACH ROW EXECUTE FUNCTION stop_recovery()"
            )
        else:
            cur.execute(
                "CREATE CONSTRAINT TRIGGER stop_recovery AFTER UPDATE ON ai_job_runs DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION stop_recovery()"
            )
    conn.commit()
    with pytest.raises(psycopg2.Error, match="injected recovery failure"):
        with ownership.prediction_execution():
            pytest.fail("must not start a new execution on failed recovery")
    assert states(conn) == before
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER stop_recovery ON ai_job_runs")
    conn.commit()
    with ownership.prediction_execution():
        pass
    assert [(r[1], r[2]) for r in states(conn)] == [("failed", "failed")] * 2


def test_base_exception_discards_owner_connection_and_next_owner_recovers(database):
    conn, _, pool, _ = database
    with pytest.raises(KeyboardInterrupt):
        with ownership.prediction_execution() as owner:
            seed(owner)
            raise KeyboardInterrupt()
    assert owner.closed and pool.returned[-1] is owner
    with ownership.prediction_execution():
        pass
    assert states(conn)[0][1:3] == ("failed", "failed")


def test_lost_owner_session_fences_writes_before_new_owner_can_recover(database):
    conn, _, _, _ = database
    with ownership.prediction_execution() as owner:
        _, run_id = seed(owner)
        # Closing only this fixture-owned session models the session's loss.
        owner.close()
        with ownership.prediction_execution():
            pass
        with pytest.raises(psycopg2.InterfaceError):
            publish(owner, run_id)
    assert states(conn)[0][1:3] == ("failed", "failed")
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM model_predictions")
        assert cur.fetchone() == (0,)


def test_real_process_exit_retains_outputs_and_releases_session_for_recovery(database):
    conn, _, _, schema = database
    child = r"""
import os
from contextlib import contextmanager
from uuid import uuid4
import psycopg2
from psycopg2 import sql
from scripts import prediction_job_execution as ownership
from scripts.agents import task_queue
from scripts.jobs import run_model_prediction as job
from tests.test_computation.test_prediction_job_execution_postgres import ClosingPool, publish

def connection():
    conn = psycopg2.connect(os.environ['FIXTURE_DSN'])
    with conn.cursor() as cur:
        cur.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(os.environ['FIXTURE_SCHEMA'])))
        cur.execute('SET ROLE fqp')
    conn.commit()
    return conn
@contextmanager
def database():
    conn = connection()
    try:
        yield conn
    finally:
        conn.close()
ownership.get_pool = lambda: ClosingPool(connection)
task_queue.get_db = database
job.fingerprint_runtime_sources = lambda *_: {}
def execute(**kwargs):
    publish(kwargs['execution_conn'], kwargs['prediction_run_id'])
    os._exit(86)
job._run_impl = execute
job.start_tracked_job = lambda code, agent, refs, **kw: task_queue.start_tracked_job(code, agent, refs)
job.run()
"""
    result = subprocess.run(
        [sys.executable, "-c", child],
        env=dict(
            os.environ,
            FIXTURE_DSN=os.environ["FQP_P106_TEST_DATABASE_URL"],
            FIXTURE_SCHEMA=schema,
        ),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert result.returncode == 86, result.stderr
    assert states(conn)[0][1:3] == ("running", "running")
    with ownership.prediction_execution():
        pass
    assert states(conn)[0][1:3] == ("failed", "failed")
    assert states(conn)[0][3]["completed_groups"] == 1


@pytest.mark.parametrize("failure", ["sql_aborted", "finalize_ack_lost"])
def test_job_exception_reconciles_aborted_sql_and_uncertain_success(database, monkeypatch, failure):
    from scripts.agents import task_queue
    from scripts.jobs import run_model_prediction as job

    conn, connection, _, _ = database

    @contextmanager
    def runtime():
        with closing(connection()) as fresh:
            yield fresh

    monkeypatch.setattr(task_queue, "get_db", runtime)
    start = task_queue.start_tracked_job
    monkeypatch.setattr(
        job, "start_tracked_job", lambda code, agent, refs, **kw: start(code, agent, refs)
    )
    monkeypatch.setattr(job, "fingerprint_runtime_sources", lambda *_: {})

    def execute(**kwargs):
        if failure == "sql_aborted":
            with kwargs["execution_conn"].cursor() as cur:
                cur.execute("SELECT 1/0")
        return {"status": "ok"}

    monkeypatch.setattr(job, "_run_impl", execute)
    if failure == "finalize_ack_lost":

        def finalize(*args, **kwargs):
            finalize_prediction_run(*args, **kwargs)
            raise psycopg2.OperationalError("successful COMMIT acknowledgement lost")

        monkeypatch.setattr(job, "finalize_prediction_run", finalize)
    with pytest.raises(psycopg2.Error):
        job.run()
    if failure == "sql_aborted":
        assert states(conn)[0][1:3] == ("failed", "failed")
    else:
        assert states(conn)[0][1:3] == ("running", "completed")
        with ownership.prediction_execution():
            pass
        assert states(conn)[0][1:3] == ("ok", "completed")
