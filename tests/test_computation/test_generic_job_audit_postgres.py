"""Generic audit lifecycle against schema13 in an isolated local PostgreSQL."""

from __future__ import annotations

import ast
import os
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Barrier
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from scripts import agent_storage as storage
from scripts import prediction_statistics as counts
from scripts.agents import task_queue
from scripts.jobs.run_scheduler import _audited_job


@pytest.fixture
def database(monkeypatch):
    dsn = os.environ.get("FQP_AUDIT_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("set FQP_AUDIT_TEST_DATABASE_URL to an isolated local audit database")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.lstrip("/").startswith("fqp_audit_test_")
    root = Path(__file__).resolve().parents[2]
    conn = psycopg2.connect(dsn)
    schema = f"generic_audit_{uuid4().hex}"
    created_role = False
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
            cur.execute((root / "sql/116_job_retry_lineage.sql").read_text())
            cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
            cur.execute("GRANT SELECT,INSERT,UPDATE ON ai_job_runs TO fqp")
            cur.execute("GRANT USAGE ON SEQUENCE ai_job_runs_id_seq TO fqp")
        conn.commit()

        def connect():
            runtime = psycopg2.connect(
                dsn, options="-c statement_timeout=5000 -c lock_timeout=2000"
            )
            with runtime.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cur.execute("SET ROLE fqp")
                cur.execute("SET TIME ZONE 'Asia/Shanghai'")
            runtime.commit()
            return runtime

        @contextmanager
        def get_db():
            with closing(connect()) as runtime:
                yield runtime

        monkeypatch.setattr(task_queue, "get_db", get_db)
        monkeypatch.setattr(counts, "get_db", get_db)
        monkeypatch.setattr("apps.backend.src.db.get_db", get_db)
        yield conn, connect
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
            if created_role:
                cur.execute("DROP ROLE fqp")
        conn.commit()
        conn.close()


def state(conn, run_id):
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM ai_job_runs WHERE id=%s", (run_id,))
        return cur.fetchone()


def start(conn, code="official_odds_snapshot"):
    return storage.start_job_run(conn, {"job_code": code})


@pytest.mark.parametrize(
    "returned,terminal",
    [
        ({"status": "ok"}, "completed"),
        ({"status": "error", "error": "missing fixture dependency"}, "failed"),
        ({"status": "partial"}, "failed"),
        ({"status": "skipped", "reason": "no candidates"}, "skipped"),
        ({"status": "no_data"}, "skipped"),
    ],
)
def test_scheduler_returned_status_is_persisted_without_closing_another_owner(
    database, returned, terminal
):
    conn, _ = database
    original_id = start(conn, code="fixture")
    original = state(conn, original_id)
    _audited_job("fixture", "固定样本", "qa_agent", lambda: returned)()
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,error_message,finished_at,output_refs FROM ai_job_runs WHERE id<>%s",
            (original_id,),
        )
        status, error, finished, refs = cur.fetchone()
    assert status == terminal and finished is not None
    assert (error is not None) == (terminal == "failed")
    assert str(returned) in refs["result"]
    assert state(conn, original_id) == original


@pytest.mark.parametrize("entry", ["tracked", "scheduler_ok", "scheduler_failed"])
def test_new_execution_never_closes_an_existing_live_same_code_run(database, entry):
    conn, connect = database
    with closing(connect()) as active:
        run_id = start(active)
        before = state(conn, run_id)
        if entry == "tracked":
            second = task_queue.start_tracked_job("official_odds_snapshot", "data_agent", {})
            assert second != run_id
            assert state(conn, second)[8] == "running"
            task_queue.finish_tracked_job(second, "completed", {"new": 1})
        else:

            def execute():
                assert state(conn, run_id) == before
                if entry == "scheduler_failed":
                    raise ValueError("fixed business failure")
                return {"fixed": 1}

            _audited_job("official_odds_snapshot", "fixed", "data_agent", execute)()
            with conn.cursor() as cur:
                cur.execute("SELECT status,error_message FROM ai_job_runs WHERE id<>%s", (run_id,))
                assert cur.fetchone() == (
                    ("failed", "fixed business failure")
                    if entry == "scheduler_failed"
                    else ("completed", None)
                )
        assert state(conn, run_id) == before
        assert storage.finish_job_run(active, run_id, "completed", {"original": 7}) is True


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "ok", "dry_run", "skipped"])
def test_late_failure_or_success_does_not_overwrite_terminal_facts(database, status):
    conn, connect = database
    with closing(connect()) as writer:
        run_id = start(writer)
        assert storage.finish_job_run(writer, run_id, status, {"saved": 7}, "original") is True
        before = state(conn, run_id)
        for late_status in ("failed", "completed"):
            assert storage.finish_job_run(writer, run_id, late_status, {"lost": 9}, "late") is False
            assert state(conn, run_id) == before
        assert storage.finish_job_run(writer, run_id + 1000, "failed") is False


@pytest.mark.parametrize("started", ["now()-interval '30 days'", "now()+interval '1 hour'", "NULL"])
def test_unrepresentable_duration_does_not_block_terminal_write(database, started):
    conn, connect = database
    with closing(connect()) as writer:
        run_id = start(writer)
        with writer.cursor() as cur:
            cur.execute(
                sql.SQL("UPDATE ai_job_runs SET started_at={} WHERE id=%s").format(
                    sql.SQL(started)
                ),
                (run_id,),
            )
        writer.commit()
        assert storage.finish_job_run(writer, run_id, "failed", error="fixed") is True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status,duration_ms,finished_at IS NOT NULL FROM ai_job_runs WHERE id=%s",
                (run_id,),
            )
            assert cur.fetchone() == ("failed", None, True)


def test_finish_clock_includes_time_spent_in_an_existing_transaction(database):
    conn, connect = database
    with closing(connect()) as writer:
        run_id = start(writer)
        with writer.cursor() as cur:
            cur.execute("SELECT now()::timestamp,pg_sleep(0.03)")
            transaction_start = cur.fetchone()[0]
        assert storage.finish_job_run(writer, run_id, "completed") is True
        with conn.cursor() as cur:
            cur.execute("SELECT finished_at,duration_ms FROM ai_job_runs WHERE id=%s", (run_id,))
            finished, duration = cur.fetchone()
            assert (finished - transaction_start).total_seconds() >= 0.025
            assert duration >= 25


def test_concurrent_finish_has_one_winner_without_mixing_status_and_output(database):
    conn, connect = database
    run_id = start(conn)
    barrier = Barrier(2)

    def finish(status):
        with closing(connect()) as writer:
            barrier.wait(timeout=5)
            return status, storage.finish_job_run(
                writer, run_id, status, {"winner": status}, status
            )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(finish, ["completed", "failed"]))
    assert sum(won for _, won in results) == 1
    winner = next(status for status, won in results if won)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,output_refs,error_message FROM ai_job_runs WHERE id=%s", (run_id,)
        )
        assert cur.fetchone() == (winner, {"winner": winner}, winner)


def test_successful_commit_acknowledgement_loss_cannot_relabel_saved_result(database):
    conn, connect = database
    with closing(connect()) as writer:
        run_id = start(writer)

        class LostAcknowledgement:
            def cursor(self):
                return writer.cursor()

            def commit(self):
                writer.commit()
                raise psycopg2.OperationalError("fixed lost commit acknowledgement")

        with pytest.raises(psycopg2.OperationalError, match="lost commit acknowledgement"):
            storage.finish_job_run(LostAcknowledgement(), run_id, "completed", {"saved": 7})
        before = state(conn, run_id)
        assert storage.finish_job_run(writer, run_id, "failed", error="late cleanup") is False
        assert state(conn, run_id) == before


def test_failed_commit_leaves_running_audit_until_explicit_failure_finish(database):
    conn, connect = database
    run_id = start(conn)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_finish() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.status='completed' THEN RAISE EXCEPTION 'fixed commit failure'; END IF;
            RETURN NEW; END $$""")
        cur.execute("""CREATE CONSTRAINT TRIGGER reject_finish AFTER UPDATE ON ai_job_runs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_finish()""")
    conn.commit()
    before = state(conn, run_id)
    with closing(connect()) as writer:
        with pytest.raises(psycopg2.errors.RaiseException, match="fixed commit failure"):
            storage.finish_job_run(writer, run_id, "completed", {"must_not_persist": 9})
        writer.rollback()
        assert state(conn, run_id) == before
        assert (
            storage.finish_job_run(writer, run_id, "failed", error="fixed commit failure") is True
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status,output_refs,error_message FROM ai_job_runs WHERE id=%s", (run_id,)
        )
        assert cur.fetchone() == ("failed", None, "fixed commit failure")


def test_count_lock_keeps_concurrency_control_without_relabeling_unowned_history(
    database, monkeypatch
):
    conn, connect = database
    old_id = start(conn, counts.JOB_CODE)
    before = state(conn, old_id)
    fixed = {
        "total": 7,
        "scope": counts.COUNT_SCOPE,
        "data_as_of": "2026-10-26T00:00:00+00:00",
        "computed_at": "2026-10-26T00:00:00+00:00",
    }
    calls = []

    def compute(_conn):
        calls.append(True)
        return fixed

    monkeypatch.setattr(counts, "compute_prediction_count", compute)
    with closing(connect()) as owner:
        with owner.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s,%s)", (913201, 114))
        assert counts.refresh_prediction_count()["status"] == "skipped"
        assert calls == []
        assert state(conn, old_id) == before
        owner.rollback()
    assert counts.refresh_prediction_count() == {"status": "ok", **fixed}
    assert len(calls) == 1
    assert state(conn, old_id) == before


def test_retry_keeps_original_failure_and_fences_its_late_finisher(database):
    conn, connect = database
    with closing(connect()) as writer:
        run_id = storage.start_job_run(
            writer,
            {
                "job_code": "fixed_generic",
                "job_name": "fixed name",
                "owner_agent": "qa_agent",
                "schedule_type": "manual",
                "environment": "test",
                "input_snapshot_refs": {"fixed": [7], "dependencies": ["fixture"]},
            },
        )
        storage.finish_job_run(writer, run_id, "failed", {"partial": 7}, "original failure")
        before = state(conn, run_id)
        new_id = storage.retry_job_run(writer, run_id)
        assert type(new_id) is int and new_id != run_id
        assert state(conn, run_id) == before
        assert storage.finish_job_run(writer, run_id, "completed", {"late": 9}) is False
        with conn.cursor() as cur:
            cur.execute(
                """SELECT job_code,job_name,owner_agent,schedule_type,environment,
                input_snapshot_refs,output_refs,status,retry_count,retry_of_run_id,
                finished_at,duration_ms,error_message,started_at IS NOT NULL
                FROM ai_job_runs WHERE id=%s""",
                (new_id,),
            )
            assert cur.fetchone() == (
                "fixed_generic",
                "fixed name",
                "qa_agent",
                "manual",
                "test",
                {"fixed": [7], "dependencies": ["fixture"]},
                None,
                "running",
                1,
                run_id,
                None,
                None,
                None,
                True,
            )
        assert storage.finish_job_run(writer, new_id, "completed", {"saved": 8}) is True
        assert state(conn, run_id) == before


@pytest.mark.parametrize("status", ["running", "completed", "ok", "cancelled", "skipped"])
def test_retry_does_not_reopen_nonfailed_runs(database, status):
    conn, connect = database
    run_id = start(conn)
    if status != "running":
        storage.finish_job_run(conn, run_id, status)
    before = state(conn, run_id)
    with closing(connect()) as writer:
        assert storage.retry_job_run(writer, run_id) is None
        assert storage.retry_job_run(writer, run_id + 1000) is None
    assert state(conn, run_id) == before


def test_retry_chain_has_one_child_per_failure_and_explicit_budget(database):
    conn, connect = database
    original = start(conn)
    storage.finish_job_run(conn, original, "failed", error="round 0")
    saved = {original: state(conn, original)}
    parent = original
    for attempt in (1, 2):
        child = storage.retry_job_run(conn, parent, max_retries=2)
        assert type(child) is int and child not in saved
        assert storage.retry_job_run(conn, parent, max_retries=2) is None
        storage.finish_job_run(conn, child, "failed", error=f"round {attempt}")
        with conn.cursor() as cur:
            cur.execute("SELECT retry_count,retry_of_run_id FROM ai_job_runs WHERE id=%s", (child,))
            assert cur.fetchone() == (attempt, parent)
        saved[child] = state(conn, child)
        parent = child
    assert storage.retry_job_run(conn, parent, max_retries=2) is None
    for run_id, before in saved.items():
        assert state(conn, run_id) == before


def test_concurrent_retry_creates_only_one_distinct_execution(database):
    conn, connect = database
    parent = start(conn)
    storage.finish_job_run(conn, parent, "failed", error="fixed")
    before = state(conn, parent)
    barrier = Barrier(2)

    def retry(_):
        with closing(connect()) as writer:
            barrier.wait(timeout=5)
            return storage.retry_job_run(writer, parent)

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(retry, range(2)))
    assert sum(type(value) is int for value in results) == 1
    child = next(value for value in results if type(value) is int)
    assert child != parent
    assert state(conn, parent) == before
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM ai_job_runs WHERE retry_of_run_id=%s", (parent,))
        assert cur.fetchall() == [(child,)]


@pytest.mark.parametrize(
    "code,refs",
    [
        ("model_prediction", {}),
        ("backtest", {}),
        ("other", {"execution_protocol": "future-owner/v1"}),
    ],
)
def test_generic_retry_does_not_forge_specialized_execution_ownership(database, code, refs):
    conn, connect = database
    parent = storage.start_job_run(conn, {"job_code": code, "input_snapshot_refs": refs})
    storage.finish_job_run(conn, parent, "failed", error="fixed")
    before = state(conn, parent)
    assert storage.retry_job_run(conn, parent) is None
    assert state(conn, parent) == before


def test_retry_commit_acknowledgement_loss_preserves_one_child_and_original(database):
    conn, connect = database
    parent = start(conn)
    storage.finish_job_run(conn, parent, "failed", {"old": 1}, "fixed")
    before = state(conn, parent)
    with closing(connect()) as writer:

        class LostAcknowledgement:
            def cursor(self):
                return writer.cursor()

            def commit(self):
                writer.commit()
                raise psycopg2.OperationalError("fixed lost retry acknowledgement")

        with pytest.raises(psycopg2.OperationalError, match="lost retry acknowledgement"):
            storage.retry_job_run(LostAcknowledgement(), parent)
        assert state(conn, parent) == before
        assert storage.retry_job_run(writer, parent) is None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,status,retry_count FROM ai_job_runs WHERE retry_of_run_id=%s", (parent,)
        )
        rows = cur.fetchall()
        assert len(rows) == 1 and rows[0][1:] == ("running", 1)


def test_failed_retry_commit_leaves_no_child_and_preserves_parent(database):
    conn, connect = database
    parent = start(conn)
    storage.finish_job_run(conn, parent, "failed", error="fixed")
    before = state(conn, parent)
    with conn.cursor() as cur:
        cur.execute("""CREATE FUNCTION reject_retry() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'fixed retry commit failure'; END $$""")
        cur.execute("""CREATE CONSTRAINT TRIGGER reject_retry AFTER INSERT ON ai_job_runs
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION reject_retry()""")
    conn.commit()
    with closing(connect()) as writer:
        with pytest.raises(psycopg2.errors.RaiseException, match="fixed retry commit failure"):
            storage.retry_job_run(writer, parent)
        writer.rollback()
    assert state(conn, parent) == before
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM ai_job_runs WHERE retry_of_run_id=%s", (parent,))
        assert cur.fetchone() == (0,)


@pytest.mark.parametrize(
    "count,budget", [(0, 0), (2, 2), (None, 2), (-1, 2), (2147483647, 2147483648)]
)
def test_retry_budget_or_unknown_legacy_count_never_resets_history(database, count, budget):
    conn, connect = database
    parent = start(conn)
    storage.finish_job_run(conn, parent, "failed", error="fixed")
    with conn.cursor() as cur:
        cur.execute("UPDATE ai_job_runs SET retry_count=%s WHERE id=%s", (count, parent))
    conn.commit()
    before = state(conn, parent)
    with closing(connect()) as writer:
        assert storage.retry_job_run(writer, parent, max_retries=budget) is None
    assert state(conn, parent) == before


def test_cli_retry_and_finish_use_distinct_ids_in_real_database(database, monkeypatch, capsys):
    from scripts.agents import cli

    conn, connect = database
    monkeypatch.setattr(cli, "get_db", task_queue.get_db)
    parent = task_queue.start_tracked_job("fixed_generic", "qa_agent", {})
    task_queue.finish_tracked_job(parent, "failed", {"old": 7}, "fixed")
    before = state(conn, parent)
    assert cli.main(["job-retry", str(parent)]) == 0
    result = ast.literal_eval(capsys.readouterr().out.strip())
    child = result["retry_run_id"]
    assert result == {"run_id": parent, "retried": True, "retry_run_id": child}
    assert child != parent
    assert cli.main(["job-finish", str(parent), "completed"]) == 0
    assert ast.literal_eval(capsys.readouterr().out.strip())["updated"] is False
    assert cli.main(["job-finish", str(child), "completed"]) == 0
    assert ast.literal_eval(capsys.readouterr().out.strip())["updated"] is True
    assert state(conn, parent) == before


def test_database_enforces_unique_parent_and_foreign_key_even_for_direct_writers(database):
    conn, connect = database
    parent = start(conn)
    storage.finish_job_run(conn, parent, "failed")
    child = storage.retry_job_run(conn, parent)
    with closing(connect()) as writer:
        for query, params, error in [
            (
                "UPDATE ai_job_runs SET retry_of_run_id=%s WHERE id=%s",
                (parent, parent),
                psycopg2.errors.CheckViolation,
            ),
            (
                "UPDATE ai_job_runs SET retry_of_run_id=%s WHERE id=%s",
                (9999999, child),
                psycopg2.errors.ForeignKeyViolation,
            ),
            (
                """INSERT INTO ai_job_runs (job_code,job_name,owner_agent,status,retry_of_run_id)
                VALUES ('fixed','fixed','qa','running',%s)""",
                (parent,),
                psycopg2.errors.UniqueViolation,
            ),
        ]:
            with pytest.raises(error), writer.cursor() as cur:
                cur.execute(query, params)
            writer.rollback()


def test_migration_preserves_existing_unlinked_audit_history(database):
    conn, connect = database
    root = Path(__file__).resolve().parents[2]
    schema = f"legacy_retry_{uuid4().hex}"
    conn.rollback()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            source = (root / "sql/13_multi_agent_codex_schema.sql").read_text()
            cur.execute(
                re.search(r"CREATE TABLE IF NOT EXISTS ai_job_runs \([\s\S]*?\n\);", source)[0]
            )
            cur.execute("""INSERT INTO ai_job_runs (job_code,job_name,owner_agent,status,
                retry_count,output_refs,error_message,started_at,finished_at)
                SELECT 'fixed','fixed','qa', CASE WHEN n%2=0 THEN 'running' ELSE 'failed' END,
                    n%3,'{"saved":7}'::jsonb,'legacy',now()-interval '30 days',now()
                FROM generate_series(1,3000) n""")
            cur.execute("SELECT row_to_json(j) FROM ai_job_runs j ORDER BY id")
            before = [row[0] for row in cur.fetchall()]
            cur.execute((root / "sql/116_job_retry_lineage.sql").read_text())
            cur.execute("SELECT row_to_json(j) FROM ai_job_runs j ORDER BY id")
            after = [row[0] for row in cur.fetchall()]
            assert len(after) == 3000
            assert all(row.pop("retry_of_run_id") is None for row in after)
            assert after == before
            cur.execute(
                "SELECT indisunique,indisvalid,indisready FROM pg_index WHERE indexrelid='idx_ai_job_runs_retry_parent'::regclass"
            )
            assert cur.fetchone() == (True, True, True)
            cur.execute(
                "SELECT convalidated FROM pg_constraint WHERE conrelid='ai_job_runs'::regclass"
            )
            assert all(row[0] for row in cur.fetchall())
        conn.commit()
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
