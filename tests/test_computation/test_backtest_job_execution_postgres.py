"""Linked ownership using actual migrations in disposable PostgreSQL only."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import Json

from scripts import backtest_job_execution as ownership
from scripts.agent_storage import start_job_run
from scripts.backtest_engine import BacktestConfig, BacktestEngine, run_backtest_from_config
from scripts.jobs import run_backtest as job


class ClosingPool:
    def __init__(self, connect):
        self.connect = connect
        self.returned = []

    def getconn(self):
        return self.connect()

    def putconn(self, conn, *, close):
        assert close is True
        conn.close()
        self.returned.append(conn)


@pytest.fixture
def database(monkeypatch):
    dsn = os.environ.get("FQP_AUDIT_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("set FQP_AUDIT_TEST_DATABASE_URL to an isolated local audit database")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.lstrip("/").startswith("fqp_audit_test_")
    conn = psycopg2.connect(dsn)
    schema = f"backtest_{uuid4().hex}"
    root = Path(__file__).resolve().parents[2]
    created_role = False
    pool = None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname='fqp'")
            if cur.fetchone() is None:
                cur.execute("CREATE ROLE fqp NOLOGIN")
                created_role = True
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            source = (root / "sql/13_multi_agent_codex_schema.sql").read_text()
            cur.execute(
                re.search(r"CREATE TABLE IF NOT EXISTS ai_job_runs \([\s\S]*?\n\);", source)[0]
            )
            cur.execute((root / "sql/19_backtest_schema.sql").read_text())
            cur.execute("INSERT INTO backtest_runs(name,status) VALUES ('legacy','running')")
            cur.execute((root / "sql/115_backtest_job_link.sql").read_text())
            cur.execute("CREATE TABLE model_versions(model_name TEXT, is_active BOOLEAN)")
            cur.execute("INSERT INTO model_versions VALUES ('fixed',true)")
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

        def connect():
            fresh = psycopg2.connect(
                dsn,
                options="-c statement_timeout=5000 -c lock_timeout=1000",
            )
            with fresh.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cur.execute("SET ROLE fqp")
                cur.execute("SET TIME ZONE 'Asia/Shanghai'")
            fresh.commit()
            return fresh

        pool = ClosingPool(connect)
        monkeypatch.setattr(ownership, "get_pool", lambda: pool)
        yield conn, connect, pool, schema
    finally:
        if pool is not None:
            assert all(c.closed for c in pool.returned)
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            if created_role:
                cur.execute("DROP ROLE fqp")
        conn.commit()
        conn.close()


def seed(conn, expected=1, statuses=("running",), *, managed=True, parent="running"):
    refs = (
        {"execution_protocol": ownership.EXECUTION_PROTOCOL, "expected_runs": expected}
        if managed
        else {}
    )
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ai_job_runs(job_code,job_name,owner_agent,status,started_at,
                   input_snapshot_refs,error_message)
               VALUES ('backtest','backtest','backtest_agent',%s,now()-interval '30 days',%s,%s)
               RETURNING id""",
            (parent, Json(refs), "original failure" if parent == "failed" else None),
        )
        job_id = cur.fetchone()[0]
        for status in statuses:
            cur.execute(
                """INSERT INTO backtest_runs(name,status,ai_job_run_id)
                   VALUES ('linked',%s,%s) RETURNING id""",
                (status, job_id),
            )
            run_id = cur.fetchone()[0]
            if status == "completed":
                cur.execute(
                    "INSERT INTO backtest_run_results(run_id,model_name,n_bets) VALUES (%s,'fixed',7)",
                    (run_id,),
                )
    conn.commit()
    return job_id


def states(conn):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT id,status,error_message,duration_ms FROM ai_job_runs ORDER BY id")
        jobs = cur.fetchall()
        cur.execute("SELECT ai_job_run_id,status FROM backtest_runs ORDER BY id")
        children = cur.fetchall()
        cur.execute("SELECT * FROM backtest_run_results ORDER BY id")
        results = cur.fetchall()
    return jobs, children, results


def fixed_result(*_args):
    return {
        "status": "ok",
        "total_bets": 7,
        "total_windows": 0,
        "windows": [],
        "aggregate": {"fixed": {"n_bets": 7, "roi": 0.1}},
    }


def test_migration_keeps_legacy_rows_and_has_valid_index_and_foreign_key(database):
    conn, connect, _, _ = database
    assert states(conn)[1] == [(None, "running")]
    with closing(connect()) as writer:
        with writer.cursor() as cur:
            with pytest.raises(psycopg2.errors.ForeignKeyViolation):
                cur.execute("INSERT INTO backtest_runs(name,ai_job_run_id) VALUES ('bad',99999)")
        writer.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT indisvalid,indisready FROM pg_index WHERE indexrelid='idx_backtest_runs_ai_job_run'::regclass"
        )
        assert cur.fetchone() == (True, True)


def test_long_live_owner_is_not_closed_by_contender_or_commit_rollback(database):
    conn, _, _, _ = database
    with ownership.backtest_execution() as owner:
        seed(owner)
        for end in (owner.commit, owner.rollback):
            end()
            assert job.run_config(BacktestConfig()) == {
                "status": "skipped",
                "reason": "backtest_execution_in_progress",
            }
            assert states(conn)[0][0][1] == "running"
            assert states(conn)[1][-1][1] == "running"
    assert owner.closed
    with ownership.backtest_execution():
        pass
    assert states(conn)[0][0][1:] == ("failed", ownership._INTERRUPTED, None)


@pytest.mark.parametrize(
    ("expected", "statuses", "final"),
    [
        (1, ("completed",), "ok"),
        (2, ("completed",), "failed"),
        (2, ("completed", "running"), "failed"),
        (2, ("completed", "completed"), "ok"),
        (1, ("failed",), "failed"),
        (0, (), "failed"),
    ],
)
def test_recovery_uses_planned_count_and_preserves_all_completed_outputs(
    database, expected, statuses, final
):
    conn, _, _, _ = database
    seed(conn, expected, statuses)
    before = states(conn)[2]
    with ownership.backtest_execution():
        pass
    jobs, children, results = states(conn)
    assert jobs[0][1] == final
    assert [s for _, s in children[1:]] == ["failed" if s == "running" else s for s in statuses]
    assert results == before
    snapshot = states(conn)
    with ownership.backtest_execution():
        pass
    assert states(conn) == snapshot


def test_failed_parent_error_and_unversioned_unlinked_history_are_preserved(database):
    conn, _, _, _ = database
    seed(conn, parent="failed")
    seed(conn, managed=False)
    with ownership.backtest_execution():
        pass
    jobs, children, _ = states(conn)
    assert jobs[0][1:3] == ("failed", "original failure")
    assert jobs[1][1] == "running"
    assert [status for _, status in children] == ["running", "failed", "running"]
    with conn.cursor() as cur:
        cur.execute("SELECT error_message FROM backtest_runs WHERE ai_job_run_id=%s", (jobs[0][0],))
        assert cur.fetchone() == ("original failure",)


@pytest.mark.parametrize("failure", ["update", "commit"])
def test_recovery_parent_and_children_rollback_together(database, failure):
    conn, _, _, _ = database
    seed(conn)
    before = states(conn)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_recovery() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected recovery failure'; END; $$""")
        clause = (
            "CREATE TRIGGER reject_recovery BEFORE"
            if failure == "update"
            else "CREATE CONSTRAINT TRIGGER reject_recovery AFTER"
        )
        deferred = " DEFERRABLE INITIALLY DEFERRED" if failure == "commit" else ""
        cur.execute(
            clause
            + " UPDATE ON ai_job_runs"
            + deferred
            + " FOR EACH ROW EXECUTE FUNCTION reject_recovery()"
        )
    conn.commit()
    with pytest.raises(psycopg2.Error, match="injected recovery failure"):
        with ownership.backtest_execution():
            pytest.fail("must not begin another execution when recovery fails")
    assert states(conn) == before
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER reject_recovery ON ai_job_runs")
    conn.commit()
    with ownership.backtest_execution():
        pass
    assert states(conn)[1][-1][1] == "failed"


def test_base_exception_discards_session_and_loss_fences_old_writes(database):
    conn, _, _, _ = database
    with pytest.raises(KeyboardInterrupt):
        with ownership.backtest_execution() as owner:
            seed(owner)
            raise KeyboardInterrupt()
    assert owner.closed
    with ownership.backtest_execution() as owner:
        seed(owner)
        owner.close()
        with ownership.backtest_execution():
            pass
        with pytest.raises(psycopg2.InterfaceError):
            run_backtest_from_config(owner, BacktestConfig(), ai_job_run_id=1)
    assert [r[1] for r in states(conn)[0]] == ["failed", "failed"]


def test_real_sweep_process_exit_preserves_completed_first_run(database):
    conn, _, _, schema = database
    child = r"""
import os
import psycopg2
from psycopg2 import sql
from scripts import backtest_job_execution as ownership
from scripts.backtest_engine import BacktestEngine
from scripts.jobs import run_backtest as job
from tests.test_computation.test_backtest_job_execution_postgres import ClosingPool, fixed_result
def connect():
    conn=psycopg2.connect(os.environ['FIXTURE_DSN'])
    with conn.cursor() as cur:
        cur.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(os.environ['FIXTURE_SCHEMA'])))
        cur.execute('SET ROLE fqp')
    conn.commit()
    return conn
ownership.get_pool=lambda: ClosingPool(connect)
calls=0
def execute(self):
    global calls
    calls+=1
    if calls==2: os._exit(86)
    return fixed_result()
BacktestEngine.run=execute
job.run(sweep=True)
"""
    child_result = subprocess.run(
        [sys.executable, "-c", child],
        env=dict(
            os.environ,
            FIXTURE_DSN=os.environ["FQP_AUDIT_TEST_DATABASE_URL"],
            FIXTURE_SCHEMA=schema,
        ),
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert child_result.returncode == 86, child_result.stderr
    before = states(conn)
    assert before[0][0][1] == "running"
    assert [s for _, s in before[1]][1:] == ["completed", "running"]
    with ownership.backtest_execution():
        pass
    assert states(conn)[0][0][1] == "failed"
    assert [s for _, s in states(conn)[1]][1:] == ["completed", "failed"]
    assert states(conn)[2] == before[2]


@pytest.mark.parametrize("mode", ["full", "model", "sweep", "manual", "dry_run"])
def test_all_entries_bind_runs_and_finish_without_a_second_writing_session(
    database, monkeypatch, mode
):
    conn, _, pool, _ = database
    monkeypatch.setattr(BacktestEngine, "run", fixed_result)
    if mode == "manual":
        result = job.run_config(BacktestConfig(name="manual"))
    else:
        result = job.run(
            model_name="fixed" if mode == "model" else None,
            sweep=mode == "sweep",
            dry_run=mode == "dry_run",
        )
    assert result["status"] == ("dry_run" if mode == "dry_run" else "ok")
    jobs, children, _ = states(conn)
    assert len(pool.returned) == 1 and jobs[0][1] == ("dry_run" if mode == "dry_run" else "ok")
    linked = children[1:]
    assert len(linked) == (0 if mode == "dry_run" else 12 if mode == "sweep" else 1)
    assert all(jid == jobs[0][0] and status == "completed" for jid, status in linked)


def test_aborted_sql_computation_records_both_failures(database, monkeypatch):
    conn, _, _, _ = database

    def execute(engine):
        with engine.conn.cursor() as cur:
            cur.execute("SELECT 1/0")

    monkeypatch.setattr(BacktestEngine, "run", execute)
    with pytest.raises(psycopg2.errors.DivisionByZero):
        job.run_config(BacktestConfig())
    assert states(conn)[0][0][1] == "failed"
    assert states(conn)[1][-1][1] == "failed"


@pytest.mark.parametrize("failure", ["insert", "commit"])
def test_result_storage_failure_rolls_back_windows_and_results(database, monkeypatch, failure):
    conn, _, _, _ = database

    def execute(_engine):
        result = fixed_result()
        result["windows"] = [
            {
                "window_index": 0,
                "train_start": None,
                "train_end": None,
                "test_start": "2026-10-01",
                "test_end": "2026-10-02",
                "n_train_matches": 0,
                "n_test_matches": 1,
                "n_bets": 7,
                "model_metrics": {"fixed": {"n_bets": 7}},
            }
        ]
        return result

    monkeypatch.setattr(BacktestEngine, "run", execute)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_result() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected storage failure'; END; $$""")
        if failure == "insert":
            cur.execute(
                "CREATE TRIGGER reject_result BEFORE INSERT ON backtest_run_results FOR EACH ROW EXECUTE FUNCTION reject_result()"
            )
        else:
            cur.execute(
                "CREATE CONSTRAINT TRIGGER reject_result AFTER INSERT ON backtest_run_results DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_result()"
            )
    conn.commit()
    result = job.run_config(BacktestConfig())
    assert result["status"] == "store_failed" and result["run_id"] is not None
    assert states(conn)[0][0][1] == "failed" and states(conn)[1][-1][1] == "failed"
    assert states(conn)[2] == []
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM backtest_run_windows")
        assert cur.fetchone() == (0,)


def test_committed_results_are_not_failed_when_commit_ack_is_lost(database, monkeypatch):
    conn, _, _, _ = database
    monkeypatch.setattr(BacktestEngine, "run", fixed_result)
    store = BacktestEngine.store_results

    def lost_ack(engine, *args):
        store(engine, *args)
        raise psycopg2.OperationalError("successful COMMIT acknowledgement lost")

    monkeypatch.setattr(BacktestEngine, "store_results", lost_ack)
    with pytest.raises(psycopg2.OperationalError, match="acknowledgement lost"):
        job.run_config(BacktestConfig())
    jobs, children, results = states(conn)
    assert jobs[0][1] == "ok" and children[-1][1] == "completed" and len(results) == 1


def test_missing_or_unversioned_owner_cannot_create_linked_run(database):
    _, connect, _, _ = database
    with closing(connect()) as writer:
        job_id = start_job_run(writer, {"job_code": "backtest"})
        with pytest.raises(RuntimeError, match="could not be created"):
            run_backtest_from_config(writer, BacktestConfig(), ai_job_run_id=job_id)


@pytest.mark.parametrize("busy", [False, True])
def test_manual_http_uses_owned_writer_and_returns_real_result(database, monkeypatch, client, busy):
    conn, _, _, _ = database
    monkeypatch.setattr(BacktestEngine, "run", fixed_result)
    if busy:
        with ownership.backtest_execution():
            response = client.post("/api/backtests", json={"model_names": ["fixed"]})
        assert response.json() == {"status": "skipped", "reason": "backtest_execution_in_progress"}
        assert states(conn)[0] == []
    else:
        response = client.post("/api/backtests", json={"model_names": ["fixed"]})
        assert response.json()["status"] == "ok" and response.json()["total_bets"] == 7
        assert states(conn)[0][0][1] == "ok" and states(conn)[1][-1][1] == "completed"
        assert response.json()["run_id"] is not None
    assert response.status_code == 200


@pytest.mark.parametrize("mode", ["full", "model"])
def test_scheduled_storage_failure_reports_original_reason(database, monkeypatch, mode):
    conn, _, _, _ = database
    monkeypatch.setattr(BacktestEngine, "run", fixed_result)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_result() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'injected storage failure'; END; $$""")
        cur.execute(
            "CREATE TRIGGER reject_result BEFORE INSERT ON backtest_run_results FOR EACH ROW EXECUTE FUNCTION reject_result()"
        )
    conn.commit()
    result = job.run(model_name="fixed" if mode == "model" else None)
    assert (
        result["status"] == "store_failed" and "injected storage failure" in result["store_error"]
    )
    assert "injected storage failure" in states(conn)[0][0][2]
