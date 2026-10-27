from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import statistics
import time
import uuid
from contextlib import closing, contextmanager, nullcontext
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlparse

import pytest
from psycopg2.errors import LockNotAvailable, RaiseException, StringDataRightTruncation


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_scheduled_count_snapshot_survives_failures_and_reads_without_history_access(
    isolated_database, monkeypatch, archive_snapshots
):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.errors import QueryCanceled

    from apps.backend.src.routers import dashboard
    from scripts import prediction_statistics as counts

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("""ALTER TABLE ai_job_runs
            ADD COLUMN job_code TEXT, ADD COLUMN job_name TEXT, ADD COLUMN owner_agent TEXT,
            ADD COLUMN schedule_type TEXT, ADD COLUMN environment TEXT,
            ADD COLUMN input_snapshot_refs JSONB, ADD COLUMN output_refs JSONB,
            ADD COLUMN status TEXT, ADD COLUMN started_at TIMESTAMP,
            ADD COLUMN finished_at TIMESTAMP, ADD COLUMN duration_ms INTEGER,
            ADD COLUMN error_message TEXT, ADD COLUMN created_at TIMESTAMP DEFAULT now()""")
        cursor.execute(
            "CREATE INDEX idx_ai_job_runs_code_time ON ai_job_runs(job_code, created_at DESC)"
        )
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher'), ('maher'), ('elo')"
        )
        cursor.execute("""INSERT INTO official_matches (kickoff_time)
            SELECT '2026-10-25 20:00'::timestamp FROM generate_series(1,100)""")
        cursor.execute(
            """INSERT INTO model_predictions (match_id, model_version_id, predict_time,
                play_type, option_code, model_probability, validation_status)
            SELECT m.id, mv.id, '2026-06-01'::timestamp + n * INTERVAL '1 minute',
                   'spf', option_code, 0.333333, 'valid'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code""",
            (archive_snapshots,),
        )
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute("GRANT SELECT ON official_matches, model_versions, model_predictions TO fqp")
        cursor.execute("GRANT SELECT, INSERT, UPDATE ON ai_job_runs TO fqp")
        cursor.execute("GRANT USAGE ON SEQUENCE ai_job_runs_id_seq TO fqp")
    conn.commit()

    @contextmanager
    def runtime_database():
        with closing(psycopg2.connect(conn.dsn)) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cursor.execute("SET ROLE fqp")
                # Timestamps must remain valid with a non-UTC session timezone.
                cursor.execute("SET TIME ZONE 'Asia/Shanghai'")
            runtime.commit()
            yield runtime

    monkeypatch.setattr(counts, "get_db", runtime_database)
    monkeypatch.setattr(dashboard, "get_db", runtime_database)
    assert dashboard.get_prediction_count()["total"] is None
    assert counts.refresh_prediction_count()["total"] == 900 * archive_snapshots
    first = dashboard.get_prediction_count()
    assert first["total"] == 900 * archive_snapshots and first["status"] == "ok"
    assert first["data_as_of"] <= first["last_success_at"]

    # Reader must work even if its role cannot access any historical predictions.
    with conn.cursor() as cursor:
        cursor.execute(
            "REVOKE SELECT ON official_matches, model_versions, model_predictions FROM fqp"
        )
    conn.commit()
    samples_ms = []
    for _ in range(30):
        started = time.perf_counter()
        assert dashboard.get_prediction_count() == first
        samples_ms.append((time.perf_counter() - started) * 1000)
    ordered = sorted(samples_ms)
    print(
        json.dumps(
            {
                "count_snapshot_archive_rows": 900 * archive_snapshots,
                "samples": 30,
                "cache": "warm",
                "concurrency": 1,
                "includes": "function plus new connection/role/timezone setup; no HTTP",
                "median_ms": statistics.median(ordered),
                "p95_ms": ordered[28],
                "max_ms": ordered[-1],
            }
        ),
        flush=True,
    )
    with conn.cursor() as cursor:
        cursor.execute("GRANT SELECT ON official_matches, model_versions, model_predictions TO fqp")
    conn.commit()

    original_compute = counts.compute_prediction_count

    def timeout_count(count_conn):
        with count_conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout = '20ms'")
            cursor.execute("SELECT pg_sleep(0.1)")

    monkeypatch.setattr(counts, "compute_prediction_count", timeout_count)
    with pytest.raises(QueryCanceled):
        counts.refresh_prediction_count()
    failed = dashboard.get_prediction_count()
    assert failed == {**first, "status": "refresh_failed"}
    with conn.cursor() as cursor:
        cursor.execute("SELECT status FROM ai_job_runs ORDER BY id")
        assert cursor.fetchall() == [("completed",), ("failed",)]
    conn.commit()

    # A second owner cannot mark a live producer interrupted or create a run.
    with runtime_database() as owner:
        with owner.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", (913201, 114))
        assert counts.refresh_prediction_count()["status"] == "skipped"
        owner.rollback()
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM ai_job_runs")
        assert cursor.fetchone()[0] == 2
        # Corrected kickoff times and deletions must be reflected by the next
        # exact count; there is no append-only increment assumption.
        cursor.execute("DELETE FROM model_predictions WHERE id = 1")
        cursor.execute("UPDATE official_matches SET kickoff_time='2026-01-01' WHERE id=2")
        cursor.execute(
            "SELECT COUNT(*) FROM model_predictions mp JOIN official_matches m "
            "ON m.id=mp.match_id WHERE mp.predict_time < m.kickoff_time"
        )
        expected = cursor.fetchone()[0]
        cursor.execute(
            """INSERT INTO ai_job_runs (job_code, status, started_at)
            VALUES (%s, 'running', now() - interval '1 day')""",
            (counts.JOB_CODE,),
        )
    conn.commit()
    monkeypatch.setattr(counts, "compute_prediction_count", original_compute)
    assert counts.refresh_prediction_count()["total"] == expected
    assert dashboard.get_prediction_count()["total"] == expected
    assert dashboard.get_prediction_count()["status"] == "ok"
    with conn.cursor() as cursor:
        cursor.execute("SELECT status FROM ai_job_runs ORDER BY id")
        # An unversioned historical run has no provable owner, even though the
        # current producer holds its own count lock. Do not relabel history.
        assert cursor.fetchall() == [("completed",), ("failed",), ("running",), ("completed",)]


@pytest.mark.parametrize("job", ["daily_review", "news_shadow"])
@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_scoped_jobs_do_not_rank_unrelated_prediction_history(
    isolated_database, monkeypatch, job, archive_snapshots
):
    from scripts import news_shadow_storage
    from scripts.jobs import generate_daily_review
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, _ = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout = '15s'")
        cursor.execute("SET TIME ZONE 'UTC'")
        cursor.execute("ALTER TABLE model_versions ADD COLUMN is_active BOOLEAN DEFAULT true")
        cursor.execute("ALTER TABLE official_matches ADD COLUMN official_match_code TEXT")
        cursor.execute("""INSERT INTO model_versions (model_name, is_active)
            VALUES ('maher_poisson', true), ('maher_poisson', true), ('elo_rating', false)""")
        cursor.execute("""INSERT INTO official_matches
            (business_date, kickoff_time, official_match_code)
            SELECT CASE WHEN n <= 100 THEN '2026-06-01'::date
                        WHEN n <= 108 THEN '2026-10-24'::date ELSE '2026-10-23'::date END,
                   '2026-10-24 20:00'::timestamp,
                   CASE WHEN n = 109 THEN NULL ELSE 'fixture-' || n END
            FROM generate_series(1,110) n""")
        cursor.execute(
            """INSERT INTO model_predictions (match_id, model_version_id, predict_time,
                play_type, option_code, model_probability, validation_status)
            SELECT m.id, mv.id, '2026-06-01'::timestamp + n * INTERVAL '1 minute',
                   'spf', option_code, 0.333333, 'valid'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id <= 100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO model_predictions (match_id, model_version_id, predict_time,
                play_type, option_code, model_probability, validation_status)
            SELECT m.id, CASE WHEN m.id = 105 THEN 3 ELSE 1 END,
                   '2026-10-24 11:00'::timestamp, 'spf', option_code,
                   CASE WHEN option_code='3' THEN 0.5 ELSE 0.25 END, 'valid'
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id > 100""")
        cursor.execute("""INSERT INTO model_predictions (match_id, model_version_id, predict_time,
                play_type, option_code, model_probability, validation_status)
            SELECT m.id, 2, CASE WHEN m.id=103 THEN '2026-10-24 21:00'::timestamp
                                WHEN m.id=107 THEN '2026-10-24 13:00'::timestamp
                                ELSE '2026-10-24 11:30'::timestamp END,
                   'spf', option_code, 0.333333,
                   CASE WHEN m.id IN (101,104) THEN 'invalid' ELSE 'valid' END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id IN (101,103,104,107) AND (m.id <> 101 OR option_code='3')""")
        cursor.execute("""CREATE INDEX idx_predictions_match
            ON model_predictions(match_id, play_type, option_code)""")
        cursor.execute("""CREATE TABLE match_news_snapshots (
            id BIGSERIAL PRIMARY KEY, match_id BIGINT, snapshot_cutoff TIMESTAMPTZ)""")
        cursor.execute("""CREATE TABLE match_news_features (
            match_id BIGINT, snapshot_id BIGINT, snapshot_label TEXT,
            home_net_impact NUMERIC, away_net_impact NUMERIC)""")
        cursor.execute("""INSERT INTO match_news_snapshots (match_id, snapshot_cutoff)
            SELECT id, '2026-10-24 12:00+08'::timestamptz FROM official_matches
            WHERE id > 100 AND id <> 108""")
        cursor.execute("""INSERT INTO match_news_features
            SELECT match_id, id, CASE WHEN match_id=110 THEN 'T120M' ELSE 'T45M' END, 0.5, 0
            FROM match_news_snapshots""")
        cursor.execute(
            (Path(__file__).resolve().parents[2] / "sql/97_news_shadow_model.sql").read_text()
        )
    conn.commit()

    # A published vector beats the newer unmapped rows of the older same-name version.
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=None,
        release_id="scoped-jobs-fixture",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[{"model_version_id": 2}],
        input_manifest={"match_ids": [102]},
        provenance_status="incomplete",
    )
    metadata = {
        "match_id": 102,
        "model_version_id": 2,
        "play_type": "spf",
        "predict_time": "2026-10-24T09:00:00",
        "feature_snapshot_id": 77,
        "expected_options": ["3", "1", "0"],
    }
    store_prediction_group(
        conn,
        run_id=run_id,
        metadata=metadata,
        predictions=[
            {
                **{k: v for k, v in metadata.items() if k != "expected_options"},
                "option_code": option,
                "model_probability": probability,
                "ev": 0,
                "validation_status": "valid",
                "calculation_version": "fixture-v1",
                "odds_snapshot_id": 30,
                "market_probability": probability,
                "break_even_probability": probability,
                "market_edge": 0,
                "breakeven_edge": 0,
            }
            for option, probability in (("3", 0.2), ("1", 0.3), ("0", 0.5))
        ],
    )
    finalize_prediction_run(
        conn,
        run_id=run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
    conn.commit()

    capture = MagicMock()
    captured_cursor = capture.cursor.return_value.__enter__.return_value
    captured_cursor.fetchone.return_value = (0,)
    captured_cursor.fetchall.return_value = []
    if job == "daily_review":
        monkeypatch.setattr(generate_daily_review, "get_db", lambda: nullcontext(capture))
        monkeypatch.setattr(
            generate_daily_review,
            "assess_daily_report_readiness",
            lambda *_: {"canGenerate": True, "status": "ready"},
        )
        monkeypatch.setattr(
            generate_daily_review, "has_completed_report_generation_run", lambda *_, **__: False
        )
        for name in (
            "upsert_daily_review",
            "generate_report",
            "build_match_review_cards",
            "upsert_report_generation_run",
            "maybe_generate_post_match_report",
            "build_daily_report_snapshot",
            "daily_summary",
        ):
            monkeypatch.setattr(generate_daily_review, name, MagicMock())
        generate_daily_review._run_impl(review_date="2026-10-24")
        query, params = next(
            call.args
            for call in captured_cursor.execute.call_args_list
            if "model_prediction_latest_rows" in call.args[0]
        )
        with conn.cursor() as cursor:
            for day, expected in (("2026-10-24", 6), ("2026-10-23", 2), ("2026-10-22", 0)):
                cursor.execute(query, (day,))
                assert cursor.fetchone() == (expected,)
            cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query, params)
            plan = cursor.fetchone()[0][0]
    else:
        assert news_shadow_storage.generate_shadow_predictions(capture) == 0
        query = captured_cursor.execute.call_args.args[0]
        with conn.cursor() as cursor:
            cursor.execute(query)
            rows = cursor.fetchall()
            assert len(rows) == 8
            assert sorted({row[0] for row in rows}) == [101, 102, 106]
            assert {row[2]: float(row[3]) for row in rows if row[0] == 102} == {
                "3": 0.2,
                "1": 0.3,
                "0": 0.5,
            }
            assert all(row[1] == 2 for row in rows if row[0] == 102)
            cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query)
            plan = cursor.fetchone()[0][0]
        # Exercise the real shadow writer, completeness gate and conflict key.
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM model_predictions")
            formal_before = cursor.fetchone()[0]
        assert news_shadow_storage.generate_shadow_predictions(conn) == 2
        assert news_shadow_storage.generate_shadow_predictions(conn) == 0
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT match_id, baseline_probabilities, shadow_probabilities "
                "FROM news_shadow_predictions ORDER BY match_id"
            )
            saved = cursor.fetchall()
            assert [row[0] for row in saved] == [102, 106]
            assert saved[0][1] == {"3": 0.2, "1": 0.3, "0": 0.5}
            assert saved[0][2] == {"3": 0.2075, "1": 0.3, "0": 0.4925}
            cursor.execute("SELECT COUNT(*) FROM model_predictions")
            assert cursor.fetchone()[0] == formal_before

    def prediction_rows_examined(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (
                node["Actual Rows"]
                + node.get("Rows Removed by Filter", 0)
                + node.get("Rows Removed by Index Recheck", 0)
            ) * node["Actual Loops"]
        return own + sum(prediction_rows_examined(child) for child in node.get("Plans", []))

    examined = prediction_rows_examined(plan["Plan"])
    print(
        json.dumps(
            {
                "job": job,
                "archive_rows": 900 * archive_snapshots,
                "prediction_rows_examined": examined,
                "execution_time_ms": plan["Execution Time"],
            }
        ),
        flush=True,
    )
    assert examined < 20000, "a bounded job must not rank unrelated prediction history"
    if archive_snapshots == 1000:
        samples_ms = []
        expected_rows = [(6,)] if job == "daily_review" else rows
        with conn.cursor() as cursor:
            for _ in range(30):
                started = time.perf_counter()
                cursor.execute(query, params if job == "daily_review" else None)
                assert cursor.fetchall() == expected_rows
                samples_ms.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples_ms)
        print(
            json.dumps(
                {
                    "job": job,
                    "archive_rows": 900 * archive_snapshots,
                    "samples": 30,
                    "cache": "warm",
                    "concurrency": 1,
                    "median_ms": statistics.median(ordered),
                    "p95_ms": ordered[28],
                    "max_ms": ordered[-1],
                }
            ),
            flush=True,
        )


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
@pytest.mark.parametrize("read_kind", ["recent", "summary", "summary_only"])
def test_recent_predictions_preserve_latest_semantics_without_ranking_archive(
    isolated_database, monkeypatch, archive_snapshots, read_kind
):
    from psycopg2 import sql

    from apps.backend.src.routers import predictions as router
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout = '15s'")
        cursor.execute("SHOW jit")
        original_jit = cursor.fetchone()[0]
    capture = MagicMock()
    captured_cursor = capture.cursor.return_value.__enter__.return_value
    captured_cursor.fetchall.return_value = []
    captured_cursor.fetchone.return_value = (0, 0, None, 0, None)
    monkeypatch.setattr(router, "get_db", lambda: nullcontext(capture))
    router.list_predictions(match_id=None, limit=200, include_summary=True)
    read_setting = captured_cursor.execute.call_args_list[0].args
    assert read_setting == ("SET LOCAL jit = off",)
    summary_query, summary_params = captured_cursor.execute.call_args.args
    with conn.cursor() as cursor:
        cursor.execute(*read_setting)
        cursor.execute(summary_query, summary_params)
        assert cursor.fetchone() == (0, 0, None, 0, None)
    router.list_predictions(match_id=None, limit=200, include_summary=False)
    query, params = captured_cursor.execute.call_args.args
    with conn.cursor() as cursor:
        cursor.execute("""ALTER TABLE model_versions ADD COLUMN version TEXT,
            ADD COLUMN model_type TEXT, ADD COLUMN feature_set_version TEXT""")
        # Only null evidence is needed here; the route's actual SQL is executed,
        # including its evidence joins, rather than testing a hand-copied query.
        feature_columns = set(re.findall(r"fs\.(\w+)", query)) - {"match_id"}
        column_types = {"id": "BIGINT", "snapshot_time": "TIMESTAMP", "feature_version": "TEXT"}
        cursor.execute(
            sql.SQL("CREATE TABLE match_feature_snapshots (match_id BIGINT, {})").format(
                sql.SQL(", ").join(
                    sql.SQL("{} {}").format(
                        sql.Identifier(name), sql.SQL(column_types.get(name, "NUMERIC"))
                    )
                    for name in sorted(feature_columns)
                )
            )
        )
        cursor.execute("""INSERT INTO model_versions (model_name)
            VALUES ('maher_poisson'), ('maher_poisson'), ('elo_rating')""")
        cursor.execute("""INSERT INTO official_matches (kickoff_time)
            SELECT '2026-10-26 18:00'::timestamp FROM generate_series(1,110)""")
        cursor.execute(
            """INSERT INTO model_predictions (
            match_id, model_version_id, predict_time, play_type, option_code,
            model_probability, ev, validation_status)
            SELECT m.id, mv.id, '2026-06-01'::timestamp + n * INTERVAL '1 minute',
                   'spf', option_code, 0.333333, n / 1000.0, 'valid'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id <= 100""",
            (archive_snapshots,),
        )
        cursor.execute("""CREATE INDEX idx_predictions_match
            ON model_predictions(match_id, play_type, option_code)""")
        cursor.execute(
            """CREATE INDEX idx_predictions_model ON model_predictions(model_version_id)"""
        )
        cursor.execute("""CREATE INDEX idx_predictions_valid_recent
            ON model_predictions(predict_time DESC, ev DESC, id DESC)
            WHERE validation_status='valid'""")
    conn.commit()

    def publish(
        match_ids,
        *,
        terminal=True,
        timestamp="2026-10-25T10:00:00",
        version_id=1,
        invalid=False,
        play_type="spf",
    ):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="recent-list-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": version_id}],
            input_manifest={"match_ids": match_ids},
            provenance_status="incomplete",
        )
        for match_id in match_ids:
            metadata = {
                "match_id": match_id,
                "model_version_id": version_id,
                "play_type": play_type,
                "predict_time": timestamp,
                "feature_snapshot_id": 77,
                "expected_options": ["3", "1", "0"],
            }
            store_prediction_group(
                conn,
                run_id=run_id,
                metadata=metadata,
                predictions=[
                    {
                        **{k: v for k, v in metadata.items() if k != "expected_options"},
                        "option_code": option,
                        "model_probability": probability,
                        "ev": 0.1,
                        "validation_status": "invalid" if invalid else "valid",
                        "calculation_version": "fixture-v1",
                        "odds_snapshot_id": 30,
                        "feature_snapshot_id": 77,
                        "market_probability": probability,
                        "break_even_probability": probability,
                        "market_edge": 0,
                        "breakeven_edge": 0,
                    }
                    for option, probability in (("3", 0.5), ("1", 0.25), ("0", 0.25))
                ],
            )
        if terminal:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": len(match_ids),
                    "completed_groups": len(match_ids),
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )

    publish(list(range(1, 101)))
    # A later invalid complete group hides the older valid vector. Equal-time
    # groups use creation/id ordering across same-name versions, for each play.
    publish([2], timestamp="2026-10-25T13:00:00", version_id=2, invalid=True)
    publish([3], version_id=2)
    publish([4], play_type="rqspf")
    publish([103], terminal=False, timestamp="2026-10-25T14:00:00")
    publish([109], terminal=False)
    with conn.cursor() as cursor:
        # Same-name model versions compete by time/id. Invalid and post-kickoff
        # latest rows must hide older valid pre-match rows, never resurrect them.
        cursor.execute("""INSERT INTO model_predictions (
            match_id, model_version_id, predict_time, play_type, option_code,
            model_probability, ev, validation_status) VALUES
            (1,2,'2026-10-25 15:00','spf','3',0.5,0.9,'valid'),
            (101,1,'2026-10-25 11:00','spf','3',0.5,0.1,'valid'),
            (101,2,'2026-10-25 12:00','spf','3',0.5,0.1,'invalid'),
            (102,1,'2026-10-25 12:00','spf','3',0.5,0.1,'valid'),
            (102,2,'2026-10-25 12:00','spf','3',0.6,0.1,'valid'),
            (103,1,'2026-10-25 12:00','spf','3',0.5,NULL,'valid'),
            (104,1,'2026-10-25 12:00','spf','3',0.5,0.1,'valid'),
            (104,2,'2026-10-26 19:00','spf','3',0.5,0.1,'valid'),
            (105,1,'2026-10-25 10:00','spf','3',0.5,0.2,'valid')""")
        cursor.execute("""INSERT INTO model_predictions (
            match_id, model_version_id, predict_time, play_type, option_code,
            model_probability, ev, validation_status) VALUES
        (106,1,'2026-10-25 10:00','spf','3',0.5,0.2,'valid'),
        (106,2,'2026-10-25 11:00','spf','3',0.5,0.2,NULL),
        (107,1,'2026-10-25 10:00','spf','3',0.5,0.2,'valid'),
        (107,2,'2026-10-26 18:00','spf','3',0.5,0.2,'valid'),
        (108,1,'2026-10-25 10:00','custom','edge',0.5,-0.2,'valid'),
        (108,2,'2026-10-25 10:00','custom','edge',0.6,0,'valid'),
        (9999,1,'2026-10-25 10:00','spf','3',0.5,0.2,'valid'),
        (108,9999,'2026-10-25 10:00','spf','3',0.5,0.2,'valid')""")
        cursor.execute("""UPDATE model_predictions SET confidence_score =
            CASE WHEN match_id = 102 THEN 0 WHEN match_id = 105 THEN 0.8 ELSE NULL END
            WHERE match_id IN (102,105,108)""")
        # Build the real migration on populated data, then replay it to check
        # idempotence. This is a bounded fixture, not production build timing.
        migration = (
            Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql"
        ).read_text()
        started = time.perf_counter()
        cursor.execute(migration)
        build_ms = (time.perf_counter() - started) * 1000
        cursor.execute(migration)
        cursor.execute("""SELECT i.indisvalid, pg_relation_size(i.indexrelid)
            FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
            WHERE c.relname='idx_predictions_identity_latest'
              AND c.relnamespace=current_schema()::regnamespace""")
        valid, index_bytes = cursor.fetchone()
        assert valid
        print(json.dumps({"identity_index_build_ms": build_ms, "index_bytes": index_bytes}))
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
        cursor.execute("ANALYZE")
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute(*read_setting)
        cursor.execute("SET LOCAL ROLE fqp")

    for match_id, limit in (
        (None, 200),
        (None, 500),
        (1, 10),
        (2, 10),
        (3, 10),
        (4, 10),
        (101, 10),
        (102, 1),
        (103, 10),
        (104, 10),
        (105, 10),
        (106, 10),
        (107, 10),
        (108, 10),
        (109, 10),
        (999, 10),
    ):
        print(
            json.dumps(
                {"archive_rows": 900 * archive_snapshots, "match_id": match_id, "limit": limit}
            ),
            flush=True,
        )
        captured_cursor.execute.reset_mock()
        router.list_predictions(
            match_id=match_id,
            limit=limit,
            include_summary=read_kind == "summary",
            summary_only=read_kind == "summary_only",
        )
        if read_kind == "summary_only":
            assert len(captured_cursor.execute.call_args_list) == 2
            assert "COUNT(*) AS total" in captured_cursor.execute.call_args_list[1].args[0]
        query, params = captured_cursor.execute.call_args.args
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            actual = (
                cursor.fetchone() if read_kind in ("summary", "summary_only") else cursor.fetchall()
            )
            cursor.execute(
                """SELECT mp.id, mp.predict_time, mp.ev, mp.confidence_score, mv.model_name
                FROM model_prediction_latest_rows mp
                JOIN model_versions mv ON mv.id=mp.model_version_id
                JOIN official_matches m ON m.id=mp.match_id
                WHERE mp.validation_status='valid' AND mp.predict_time < m.kickoff_time
                  AND (%s::bigint IS NULL OR mp.match_id=%s)
                ORDER BY mp.predict_time DESC, mp.ev DESC, mp.id DESC""",
                (match_id, match_id),
            )
            eligible = cursor.fetchall()
            if read_kind in ("summary", "summary_only"):
                confidence = [row[3] for row in eligible if row[3] is not None]
                expected = (
                    len(eligible),
                    sum(row[2] is not None and row[2] > 0 for row in eligible),
                    sum(confidence) / len(confidence) if confidence else None,
                    len({row[4] for row in eligible}),
                    max((row[1] for row in eligible), default=None),
                )
                assert actual[:2] == expected[:2]
                if confidence:
                    assert actual[2] == pytest.approx(expected[2])
                else:
                    assert actual[2] is None
                assert actual[3:] == expected[3:]
            else:
                assert len(actual) == min(len(eligible), limit)
                assert [row[0] for row in actual] == [row[0] for row in eligible[:limit]]
                assert [(row[2], row[10]) for row in actual] == [
                    row[1:3] for row in eligible[:limit]
                ]
            if match_id is None and limit == 200:
                cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query, params)
                plan = cursor.fetchone()[0][0]
                benchmark_query, benchmark_params = query, params

    def prediction_rows_examined(node):
        count = 0
        if node.get("Relation Name") == "model_predictions":
            count += (
                node["Actual Rows"]
                + node.get("Rows Removed by Filter", 0)
                + node.get("Rows Removed by Index Recheck", 0)
            ) * node["Actual Loops"]
        return count + sum(prediction_rows_examined(child) for child in node.get("Plans", []))

    assert "JIT" not in plan
    examined = prediction_rows_examined(plan["Plan"])
    print(
        json.dumps(
            {
                "archive_rows": 900 * archive_snapshots,
                "read_kind": read_kind,
                "prediction_rows_examined": examined,
                "execution_time_ms": plan["Execution Time"],
            }
        )
    )
    if examined >= 20000:
        print("SLOW_PLAN " + json.dumps(plan), flush=True)
    assert examined < 20000, "a prediction read must not scan/rank the full prediction archive"
    if archive_snapshots == 1000:
        samples_ms = []
        with conn.cursor() as cursor:
            for _ in range(30):
                started = time.perf_counter()
                cursor.execute(benchmark_query, benchmark_params)
                expected_rows = 1 if read_kind in ("summary", "summary_only") else 200
                assert len(cursor.fetchall()) == expected_rows
                samples_ms.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples_ms)
        print(
            json.dumps(
                {
                    "archive_rows": 900 * archive_snapshots,
                    "read_kind": read_kind,
                    "samples": len(ordered),
                    "cache": "warm",
                    "concurrency": 1,
                    "min_ms": ordered[0],
                    "median_ms": statistics.median(ordered),
                    "p95_ms": ordered[28],
                    "max_ms": ordered[-1],
                }
            )
        )

    with conn.cursor() as cursor:
        cursor.execute("SHOW jit")
        assert cursor.fetchone()[0] == "off"
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("SHOW jit")
        assert cursor.fetchone()[0] == original_jit


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_performance_refresh_scopes_latest_rows_before_ranking_archive(
    isolated_database, archive_snapshots
):
    from scripts import model_performance as performance
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, _ = isolated_database
    migrations = Path(__file__).resolve().parents[2] / "sql"
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout = '15s'")
        cursor.execute("ALTER TABLE official_matches ADD COLUMN updated_at TIMESTAMPTZ")
        cursor.execute("""ALTER TABLE official_results
            ADD COLUMN updated_at TIMESTAMPTZ, ADD COLUMN rqspf_result TEXT,
            ADD COLUMN total_goals_result TEXT, ADD COLUMN score_result TEXT,
            ADD COLUMN half_full_result TEXT""")
        cursor.execute("ALTER TABLE official_odds_snapshots ADD COLUMN handicap NUMERIC")
        cursor.execute("""INSERT INTO model_versions (model_name)
            VALUES ('maher_poisson'), ('maher_poisson'), ('elo_rating')""")
        cursor.execute("""INSERT INTO official_matches (business_date, kickoff_time, updated_at)
            SELECT CURRENT_DATE - CASE WHEN n <= 100 THEN 1500 ELSE 1 END,
                   (CURRENT_DATE - 1) + TIME '18:00', NOW() - INTERVAL '10 days'
            FROM generate_series(1,103) n""")
        cursor.execute(
            """INSERT INTO model_predictions (
                match_id, model_version_id, predict_time, play_type, option_code,
                model_probability, validation_status, uncertainty_reason)
            SELECT m.id, mv.id, CURRENT_DATE - INTERVAL '1500 days' + n * INTERVAL '1 minute',
                   'spf', option_code, 0.333333, 'valid', '{"model_independent":true}'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id <= 100""",
            (archive_snapshots,),
        )
        cursor.execute("""CREATE INDEX idx_predictions_match
            ON model_predictions(match_id, play_type, option_code)""")
        cursor.execute("""INSERT INTO official_results (
            match_id, result_status, spf_result, full_home_goals, full_away_goals,
            total_goals_result, score_result, half_full_result, updated_at)
            SELECT id, 'confirmed', CASE WHEN id=101 THEN '3' ELSE '0' END,
                1, 0, '1', '1:0', '3-3', NOW()-INTERVAL '10 days'
            FROM official_matches WHERE id>100""")
        cursor.execute("""INSERT INTO model_predictions (
            match_id, model_version_id, play_type, option_code, model_probability,
            predict_time, validation_status, uncertainty_reason)
            SELECT match_id, version_id, play, option, probability,
                   (CURRENT_DATE-1) + prediction_time, status,
                   jsonb_build_object('model_independent', independent)
            FROM (VALUES
                (101,1,'spf','3',0.6,TIME '10:00','valid',true),
                (101,2,'spf','3',0.6,TIME '11:00','valid',true),
                (101,2,'spf','0',0.4,TIME '11:00','valid',true),
                (101,3,'spf','0',0.7,TIME '11:00','valid',true),
                (101,1,'bf','1:0',0.5,TIME '10:00','valid',true),
                (101,2,'score','1:0',0.6,TIME '11:00','valid',true),
                (101,2,'score','0:0',0.4,TIME '11:00','valid',true),
                (101,1,'total_goals','1',0.7,TIME '11:00','valid',true),
                (101,1,'half_full','33',0.7,TIME '11:00','valid',true),
                (101,1,'rqspf','3',0.6,TIME '11:00','valid',true),
                (102,2,'spf','3',0.9,TIME '13:00','valid',true),
                (103,1,'spf','3',0.6,TIME '10:00','valid',true),
                (103,2,'spf','3',0.8,TIME '11:00','invalid',true),
                (103,3,'spf','3',0.7,TIME '10:00','valid',true),
                (103,3,'spf','3',0.8,TIME '19:00','valid',true),
                (103,1,'bf','1:0',0.7,TIME '10:00','valid',true),
                (103,2,'bf','1:0',0.8,TIME '11:00','valid',false)
            ) p(match_id, version_id, play, option, probability, prediction_time, status, independent)
        """)
        cursor.execute("""INSERT INTO official_odds_snapshots
            (match_id, play_type, option_code, sp_value, snapshot_time, handicap)
            VALUES (101,'rqspf','h',2,(CURRENT_DATE-1)+TIME '11:00',1)""")
    conn.commit()
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=None,
        release_id="performance-scope-fixture",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[{"model_version_id": 1}],
        input_manifest={"match_ids": [102]},
        provenance_status="incomplete",
    )
    with conn.cursor() as cursor:
        cursor.execute("SELECT (CURRENT_DATE-1)+TIME '10:00'")
        predicted_at = cursor.fetchone()[0].isoformat()
    metadata = {
        "match_id": 102,
        "model_version_id": 1,
        "play_type": "spf",
        "predict_time": predicted_at,
        "feature_snapshot_id": 77,
        "expected_options": ["3", "1", "0"],
    }
    store_prediction_group(
        conn,
        run_id=run_id,
        metadata=metadata,
        predictions=[
            {
                **{key: value for key, value in metadata.items() if key != "expected_options"},
                "option_code": option,
                "model_probability": probability,
                "validation_status": "valid",
                "calculation_version": "fixture-v1",
                "odds_snapshot_id": 30,
                "market_probability": probability,
                "break_even_probability": probability,
                "market_edge": 0,
                "breakeven_edge": 0,
                "ev": 0.1,
                "uncertainty_reason": {"model_independent": True},
            }
            for option, probability in (("3", 0.2), ("1", 0.2), ("0", 0.6))
        ],
    )
    finalize_prediction_run(
        conn,
        run_id=run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )
    with conn.cursor() as cursor:
        cursor.execute((migrations / "103_model_performance_scored_picks.sql").read_text())
        cursor.execute((migrations / "105_model_performance_dirty_matches.sql").read_text())
        cursor.execute("""UPDATE model_performance_scored_picks_state
            SET full_refreshed_at=NOW(), last_refreshed_at=NOW()-INTERVAL '3 hours'""")
        cursor.execute("""INSERT INTO model_performance_dirty_matches(match_id)
            VALUES (101),(102),(103)""")
        cursor.execute("""INSERT INTO model_performance_scored_picks
            (match_id,business_date,model_name,play_type,is_correct)
            VALUES (5,CURRENT_DATE-1500,'untouched','spf',1),
                   (103,CURRENT_DATE-1,'obsolete','spf',1)""")
        cursor.execute("ANALYZE")
    conn.commit()

    expected = [
        (101, "elo_rating", "spf", 0),
        (101, "maher_poisson", "bf", 1),
        (101, "maher_poisson", "bqc", 1),
        (101, "maher_poisson", "rqspf", 1),
        (101, "maher_poisson", "spf", 1),
        (101, "maher_poisson", "zjq", 1),
        (102, "maher_poisson", "spf", 1),
    ]
    result = performance.refresh_model_performance_scored_picks(conn, days=365)
    assert result == {
        "status": "ok",
        "refresh_type": "incremental",
        "matches_refreshed": 3,
        "scored_picks_written": 7,
    }
    with conn.cursor() as cursor:
        cursor.execute("""SELECT match_id,model_name,play_type,is_correct
            FROM model_performance_scored_picks ORDER BY match_id,model_name,play_type""")
        assert cursor.fetchall() == [(5, "untouched", "spf", 1), *expected]
        cursor.execute("SELECT COUNT(*) FROM model_performance_dirty_matches")
        assert cursor.fetchone()[0] == 0
        cursor.execute("""CREATE TEMP TABLE model_performance_refresh_settled ON COMMIT DROP AS
            SELECT m.id AS match_id,m.business_date,m.kickoff_time,r.spf_result,r.rqspf_result,
                r.full_home_goals,r.full_away_goals,r.total_goals_result,r.score_result,r.half_full_result
            FROM official_matches m JOIN official_results r ON r.match_id=m.id WHERE m.id>100""")
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + performance._REFRESH_SETTLED_PICKS_SQL)
        plan = cursor.fetchone()[0][0]
    # Raw compatibility reads and incremental writes share the scoring CTEs.
    direct = performance.get_model_performance_history(conn, days=365)
    compact = performance.get_model_performance_history_auto(conn, days=365)
    assert {key: compact[key] for key in direct} == direct

    def examined_rows(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(examined_rows(child) for child in node.get("Plans", []))

    examined = examined_rows(plan["Plan"])
    print(
        json.dumps(
            {
                "archive_rows": archive_snapshots * 900,
                "prediction_rows_examined": examined,
                "execution_time_ms": plan["Execution Time"],
                "jit": plan.get("JIT"),
            }
        ),
        flush=True,
    )
    assert examined < 20000, "a three-match refresh must not rank unrelated prediction history"

    # The EXPLAIN ANALYZE above executed an INSERT and created its own temporary
    # target table. End that diagnostic transaction before invoking the job.
    conn.rollback()
    full = performance.refresh_model_performance_scored_picks(conn, days=365, force_full=True)
    assert full["refresh_type"] == "full" and full["scored_picks_written"] == 7
    empty = performance.refresh_model_performance_scored_picks(conn, days=365)
    assert empty["matches_refreshed"] == empty["scored_picks_written"] == 0
    with conn.cursor() as cursor:
        cursor.execute("""SELECT match_id,model_name,play_type,is_correct
            FROM model_performance_scored_picks ORDER BY match_id,model_name,play_type""")
        assert cursor.fetchall() == expected


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_market_baseline_only_reads_matches_in_the_evaluation_scope(
    isolated_database, archive_snapshots
):
    from scripts.model_evaluation_scope import MARKET_BASELINE_BRIER_CTES

    conn, _ = isolated_database
    query = (
        "WITH latest_metrics AS (SELECT match_id FROM (VALUES (101),(102)) scope(match_id)) "
        + MARKET_BASELINE_BRIER_CTES
        + """ SELECT match_id,brier_score FROM market_baseline_scores
            WHERE match_id IN (SELECT match_id FROM latest_metrics) ORDER BY match_id"""
    )
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='15s'")
        cursor.execute("""INSERT INTO model_versions(model_name)
            VALUES ('market_baseline'),('market_baseline'),('maher_poisson')""")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-26 18:00'::timestamp FROM generate_series(1,103)""")
        cursor.execute(
            """INSERT INTO model_predictions(match_id,model_version_id,predict_time,
                play_type,option_code,model_probability,validation_status)
            SELECT m.id,mv.id,'2026-06-01'::timestamp+n*INTERVAL '1 minute',
                'spf',option_code,0.333333,'valid'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""CREATE INDEX idx_predictions_match
            ON model_predictions(match_id,play_type,option_code)""")
        cursor.execute("""INSERT INTO official_results(match_id,result_status,spf_result)
            VALUES (101,'confirmed','3'),(102,'confirmed','0'),(103,'confirmed','3')""")
        cursor.execute("""INSERT INTO model_predictions(match_id,model_version_id,predict_time,
            play_type,option_code,model_probability,validation_status)
            SELECT match_id,version_id,'2026-10-25'::date+prediction_time,
                'spf',option_code,probability,status
            FROM (VALUES
                (101,1,TIME '10:00','3',0.8,'valid'),
                (101,1,TIME '10:00','1',0.1,'valid'),
                (101,1,TIME '10:00','0',0.1,'valid'),
                (101,2,TIME '11:00','3',0.5,'valid'),
                (101,2,TIME '11:00','1',0.25,'valid'),
                (101,2,TIME '11:00','0',0.25,'valid'),
                (102,1,TIME '10:00','3',0.2,'valid'),
                (102,1,TIME '10:00','1',0.2,'valid'),
                (102,1,TIME '10:00','0',0.6,'valid'),
                (102,2,TIME '11:00','3',0.2,'invalid'),
                (103,1,TIME '10:00','3',0.5,'valid'),
                (103,1,TIME '10:00','1',0.25,'valid'),
                (103,1,TIME '10:00','0',0.25,'valid')
            ) p(match_id,version_id,prediction_time,option_code,probability,status)""")
        cursor.execute("ANALYZE")
        cursor.execute(query)
        actual = cursor.fetchall()
        # Missing/invalid latest baseline outcomes cannot become a zero score.
        # A confirmed match without any evaluated model is outside this scope.
        assert [(row[0], float(row[1])) for row in actual] == [(101, 0.375)]
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query)
        plan = cursor.fetchone()[0][0]

    def examined_rows(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(examined_rows(child) for child in node.get("Plans", []))

    examined = examined_rows(plan["Plan"])
    print(
        json.dumps(
            {
                "archive_rows": archive_snapshots * 900,
                "prediction_rows_examined": examined,
                "execution_time_ms": plan["Execution Time"],
            }
        ),
        flush=True,
    )
    assert examined < 20000, "paired market scores must not rank unrelated prediction history"

    # Exercise the real summary query as well as its shared baseline CTE.
    from scripts.feature_importance import get_evaluation_summary

    with conn.cursor() as cursor:
        cursor.execute("""CREATE TABLE market_efficiency_metrics (
            id BIGSERIAL PRIMARY KEY, match_id BIGINT, model_version_id BIGINT,
            play_type TEXT, snapshot_time TIMESTAMP, brier_score NUMERIC,
            log_loss NUMERIC, rps NUMERIC, clv_score NUMERIC, probability_gap NUMERIC)""")
        cursor.execute("""INSERT INTO market_efficiency_metrics
            (match_id,model_version_id,play_type,snapshot_time,brier_score,log_loss,rps)
            VALUES (101,3,'spf','2026-10-25 11:00',0.3,0.4,0.1),
                   (102,3,'spf','2026-10-25 11:00',0.2,0.3,0.1)""")
    summary = get_evaluation_summary(conn)
    assert len(summary["models"]) == 1
    model = summary["models"][0]
    assert model["n"] == summary["overall"]["total_evaluated"] == 2
    assert model["avg_brier"] == summary["overall"]["overall_brier"] == 0.25
    assert model["paired_market_samples"] == 1
    assert model["brier_improvement_vs_market"] == 0.075
    assert model["brier_improvement_ci_low"] is model["brier_improvement_ci_high"] is None
    if archive_snapshots == 1000:
        samples_ms = []
        for _ in range(30):
            started = time.perf_counter()
            assert get_evaluation_summary(conn) == summary
            samples_ms.append((time.perf_counter() - started) * 1000)
        ordered = sorted(samples_ms)
        print(
            json.dumps(
                {
                    "summary_samples": 30,
                    "archive_rows": 900000,
                    "metric_rows": 2,
                    "cache": "warm",
                    "concurrency": 1,
                    "median_ms": statistics.median(ordered),
                    "p95_ms": ordered[28],
                    "max_ms": ordered[-1],
                }
            ),
            flush=True,
        )


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_condition_statistics_only_rank_predictions_for_evaluated_matches(
    isolated_database, archive_snapshots
):
    from psycopg2 import sql

    from scripts import feature_importance
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    migrations = Path(__file__).resolve().parents[2] / "sql"
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("SET jit=off")
        # The minimal run fixture omits the base schema's read indexes. Use the
        # actual existing DDL, so this is not a new product index or migration.
        match_index = re.search(
            r"CREATE INDEX IF NOT EXISTS idx_predictions_match\b[^;]+;",
            (migrations / "06_indexes_constraints.sql").read_text(),
        )
        assert match_index is not None
        cursor.execute(match_index[0])
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same'),('other')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-26 18:00'::timestamp FROM generate_series(1,136)""")
        cursor.execute("""INSERT INTO official_results(match_id,result_status,spf_result)
            SELECT id,'confirmed','3' FROM official_matches WHERE id>100""")
        cursor.execute("""CREATE TABLE market_efficiency_metrics (
            id BIGSERIAL PRIMARY KEY, match_id BIGINT NOT NULL, model_version_id BIGINT,
            play_type TEXT NOT NULL, snapshot_time TIMESTAMP NOT NULL,
            brier_score NUMERIC, log_loss NUMERIC)""")
        cursor.execute((migrations / "114_evaluation_read_paths.sql").read_text())
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,confidence_score,validation_status)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute',
                   'spf',o,0.333333,0.333333,0.5,'valid'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        for case in range(12):
            for repeat in range(3):
                match_id = 101 + case * 3 + repeat
                version = 2 if case == 6 else 1
                when = "2026-10-25 09:00" if case == 6 else "2026-10-25 10:00"
                market, confidence = ((0.2, None), (0.4, 0), (0.6, 0.6), (0.8, 0.9))[case % 4]
                if case == 10:
                    market, confidence = None, 0.4
                cursor.execute(
                    """INSERT INTO market_efficiency_metrics
                        (match_id,model_version_id,play_type,snapshot_time,brier_score,log_loss)
                    VALUES (%s,%s,'spf',%s,0.6,1)""",
                    (match_id, version, when),
                )
                if case != 9:  # A scored match without a prediction must stay excluded.
                    cursor.execute(
                        """INSERT INTO model_predictions
                            (match_id,model_version_id,predict_time,play_type,option_code,
                             model_probability,market_probability,confidence_score,validation_status)
                        VALUES (%s,%s,%s,'spf','3',0.5,%s,%s,'valid')""",
                        (match_id, version, when, market, confidence),
                    )
                if case in (4, 5, 6, 8, 11):
                    # Keep canonical view semantics: a newer invalid row must
                    # not revive an old valid row; newer times/versions can
                    # remove the exact evaluation-snapshot association.
                    cursor.execute(
                        """INSERT INTO model_predictions
                            (match_id,model_version_id,predict_time,play_type,option_code,
                             model_probability,market_probability,confidence_score,validation_status)
                        VALUES (%s,%s,%s,%s,'3',0.9,0.9,0.9,%s)""",
                        (
                            match_id,
                            2 if case == 8 else version,
                            when if case in (4, 8) else "2026-10-25 11:00",
                            "rqspf" if case == 11 else "spf",
                            "invalid" if case == 4 else "valid",
                        ),
                    )
    conn.commit()

    # Published groups override newer legacy rows; unfinished groups must not
    # hide the older unmapped prediction. Exercise the real publication code.
    for case, completed in ((6, True), (7, False)):
        for match_id in range(101 + case * 3, 104 + case * 3):
            version = 2 if completed else 1
            run_id = uuid.uuid4()
            create_prediction_run(
                conn,
                run_id=run_id,
                ai_job_run_id=None,
                release_id="condition-fixture",
                code_fingerprint={"files": {}, "sha256": content_sha256({})},
                model_manifest=[{"model_version_id": version}],
                input_manifest={"match_ids": [match_id]},
                provenance_status="incomplete",
            )
            metadata = {
                "match_id": match_id,
                "model_version_id": version,
                "play_type": "spf",
                "predict_time": "2026-10-25T09:00:00" if completed else "2026-10-25T11:00:00",
                "feature_snapshot_id": 77,
                "expected_options": ["3", "1", "0"],
            }
            store_prediction_group(
                conn,
                run_id=run_id,
                metadata=metadata,
                predictions=[
                    {
                        **{k: v for k, v in metadata.items() if k != "expected_options"},
                        "option_code": option,
                        "model_probability": probability,
                        "market_probability": probability,
                        "confidence_score": None,
                        "validation_status": "valid",
                        "calculation_version": "condition-fixture",
                        "odds_snapshot_id": 30,
                        "break_even_probability": probability,
                        "market_edge": 0,
                        "breakeven_edge": 0,
                        "ev": 0,
                    }
                    for option, probability in (("3", 0.6), ("1", 0.25), ("0", 0.15))
                ],
            )
            if completed:
                finalize_prediction_run(
                    conn,
                    run_id=run_id,
                    run_status="completed",
                    output_summary={
                        "expected_groups": 1,
                        "completed_groups": 1,
                        "skipped_groups": 0,
                        "missing_groups": [],
                        "input_updates_skipped": 0,
                        "completion_reason": "predictions_completed",
                    },
                )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()

    class CapturedConnection:
        query = ""

        @contextmanager
        def cursor(self):
            with conn.cursor() as cursor:

                class CapturedCursor:
                    def execute(self, query):
                        captured.query = query
                        cursor.execute(query)

                    def __getattr__(self, name):
                        return getattr(cursor, name)

                yield CapturedCursor()

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    captured = CapturedConnection()
    measurements = []
    for dimension, column, expression in (
        (
            "odds_range",
            "odds_range",
            """CASE WHEN mp_home.market_probability<0.30 THEN '低概率 (<30%)'
                WHEN mp_home.market_probability<0.45 THEN '中低概率 (30-45%)'
                WHEN mp_home.market_probability<0.55 THEN '中概率 (45-55%)'
                WHEN mp_home.market_probability<0.70 THEN '中高概率 (55-70%)'
                ELSE '高概率 (>70%)' END""",
        ),
        (
            "confidence",
            "confidence_range",
            """CASE WHEN mp_home.confidence_score IS NULL THEN '未校准/未知'
                WHEN mp_home.confidence_score<0.3 THEN '低信心 (<30%)'
                WHEN mp_home.confidence_score<0.5 THEN '中低信心 (30-50%)'
                WHEN mp_home.confidence_score<0.7 THEN '中高信心 (50-70%)'
                ELSE '高信心 (>70%)' END""",
        ),
    ):
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE fqp")
        response = feature_importance.get_condition_performance(captured, dimension)
        assert sum(segment["n"] for segment in response["segments"]) == 27
        with conn.cursor() as cursor:
            # Independent original join, with no match-bound prediction CTE.
            reference_query = (
                feature_importance._LATEST_METRICS_CTE
                + f""" SELECT {expression} AS {column}, mem.canonical_model_name AS model_name,
                    COUNT(*) AS n, ROUND(AVG(mem.brier_score)::numeric,4) AS avg_brier
                FROM latest_metrics mem
                JOIN model_prediction_latest_rows mp_home ON mp_home.match_id=mem.match_id
                    AND mp_home.model_version_id=mem.model_version_id
                    AND mp_home.play_type=mem.play_type AND mp_home.option_code='3'
                    AND mp_home.predict_time=mem.snapshot_time
                WHERE mem.brier_score IS NOT NULL
                GROUP BY {column},mem.canonical_model_name HAVING COUNT(*)>=3
                ORDER BY {column},avg_brier ASC"""
            )
            cursor.execute(reference_query)
            names = [description[0] for description in cursor.description]
            expected = [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
            assert response == {"status": "ok", "dimension": dimension, "segments": expected}
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + reference_query)
            reference_plan = cursor.fetchone()[0][0]
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + captured.query)
            plan = cursor.fetchone()[0][0]
            measurements.append(
                {
                    "dimension": dimension,
                    "archive_rows": 900 * archive_snapshots,
                    "original_prediction_node_work": prediction_work(reference_plan["Plan"]),
                    "original_execution_ms": reference_plan["Execution Time"],
                    "prediction_node_work": prediction_work(plan["Plan"]),
                    "execution_ms": plan["Execution Time"],
                }
            )
    print(json.dumps({"condition_reads": measurements}), flush=True)
    conn.rollback()  # Drop the restricted role before fixture-only deletion.
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM market_efficiency_metrics")
        cursor.execute("SET LOCAL ROLE fqp")
    for dimension in ("odds_range", "confidence"):
        assert feature_importance.get_condition_performance(captured, dimension)["segments"] == []
        with conn.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + captured.query)
            assert prediction_work(cursor.fetchone()[0][0]["Plan"]) == 0
    assert all(measurement["prediction_node_work"] < 1000 for measurement in measurements)


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_error_and_calibration_reads_seek_latest_before_applying_eligibility(
    isolated_database, archive_snapshots, monkeypatch
):
    from psycopg2 import sql

    from scripts import feature_importance
    from scripts.jobs import analyze_prediction_errors
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    migrations = Path(__file__).resolve().parents[2] / "sql"
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("SET jit=off")
        # Exercise the actual already-published seek index, not a test-only fix.
        cursor.execute((migrations / "113_prediction_read_paths.sql").read_text())
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same'),('other')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-26 18:00'::timestamp FROM generate_series(1,114)""")
        for column in ("rqspf_result", "total_goals_result", "score_result", "half_full_result"):
            cursor.execute(
                sql.SQL("ALTER TABLE official_results ADD COLUMN {} TEXT").format(
                    sql.Identifier(column)
                )
            )
        cursor.execute("""INSERT INTO official_results
            (match_id,result_status,spf_result,full_home_goals,full_away_goals,rqspf_result)
            SELECT id, CASE WHEN id=110 THEN 'pending'
                           WHEN id%2=0 THEN 'final' ELSE 'confirmed' END,
                   CASE WHEN id=109 THEN NULL WHEN id IN (106,108,114) THEN '1'
                        WHEN id=107 THEN '0' ELSE '3' END,
                   CASE WHEN id=107 THEN 0 WHEN id IN (106,108,114) THEN 1 ELSE 2 END,
                   CASE WHEN id IN (106,107,108,114) THEN 1 ELSE 0 END,'3'
            FROM official_matches WHERE id<>111""")
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,validation_status,uncertainty_reason)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute',
                   'spf',o,0.333333,0.333333,'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,validation_status,uncertainty_reason)
            SELECT m.id,1,'2026-10-25'::timestamp+m.id*INTERVAL '1 minute',
                   CASE WHEN m.id=112 THEN 'rqspf' ELSE 'spf' END,o,
                   CASE WHEN o='3' THEN CASE WHEN m.id=114 THEN 0.45 ELSE 0.61 END
                        WHEN o='1' THEN CASE WHEN m.id=114 THEN 0.3 ELSE 0.24 END
                        ELSE CASE WHEN m.id=114 THEN 0.25 ELSE 0.15 END END,
                   0.333333,0.1,'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o WHERE m.id>100""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            SELECT m.id,2,CASE WHEN m.id=103 THEN '2026-10-27'::timestamp
                              WHEN m.id=108 THEN '2026-10-25'::timestamp
                                                +m.id*INTERVAL '1 minute'
                              ELSE '2026-10-25 12:00'::timestamp END,'spf',o,
                   CASE WHEN m.id=105 THEN NULL WHEN o='1' THEN 0.6 ELSE 0.2 END,
                   CASE WHEN m.id=102 THEN 'invalid' ELSE 'valid' END,
                   CASE WHEN m.id=104 THEN '{"model_independent":false}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id IN (102,103,104,105,108) AND (m.id<>105 OR o='3')""")
    conn.commit()

    # Use real publication boundaries: complete wins over newer legacy;
    # unfinished rows are invisible; a published post-match set shields legacy.
    for match_id, completed in ((106, True), (107, False), (113, True)):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="evaluation-reads-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": 2}],
            input_manifest={"match_ids": [match_id]},
            provenance_status="incomplete",
        )
        metadata = {
            "match_id": match_id,
            "model_version_id": 2,
            "play_type": "spf",
            "predict_time": "2026-10-27T12:00:00" if match_id == 113 else "2026-10-24T12:00:00",
            "feature_snapshot_id": 77,
            "expected_options": ["3", "1", "0"],
        }
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata=metadata,
            predictions=[
                {
                    **{key: value for key, value in metadata.items() if key != "expected_options"},
                    "option_code": option,
                    "model_probability": probability,
                    "market_probability": probability,
                    "validation_status": "valid",
                    "calculation_version": "evaluation-fixture",
                    "odds_snapshot_id": 30,
                    "break_even_probability": probability,
                    "market_edge": 0,
                    "breakeven_edge": 0,
                    "ev": 0,
                    "uncertainty_reason": {"model_independent": True},
                }
                for option, probability in (("3", 0.1), ("1", 0.25), ("0", 0.65))
            ],
        )
        if completed:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": 1,
                    "completed_groups": 1,
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()

    # Frozen pre-repair scope: the oracle keeps ranking all legacy history in
    # the canonical view. Only the caller's unchanged projection is reused.
    original_scope = """WITH latest_predictions AS (
        SELECT DISTINCT ON (source_mp.match_id,source_mv.model_name,
                            source_mp.play_type,source_mp.option_code)
               source_mp.*,source_mv.model_name AS canonical_model_name
        FROM model_prediction_latest_rows source_mp
        JOIN model_versions source_mv ON source_mv.id=source_mp.model_version_id
        JOIN official_matches source_match ON source_match.id=source_mp.match_id
        JOIN official_results source_result ON source_result.match_id=source_mp.match_id
        WHERE source_mp.predict_time<source_match.kickoff_time
          AND source_mp.validation_status='valid'
          AND COALESCE((source_mp.uncertainty_reason->>'model_independent')::boolean,false)=true
          AND source_result.result_status IN ('final','confirmed')
        ORDER BY source_mp.match_id,source_mv.model_name,source_mp.play_type,
                 source_mp.option_code,source_mp.predict_time DESC,source_mp.id DESC
    )"""
    writes = []

    class CapturedConnection:
        query = ""
        params = None
        rows = None
        reference = False

        @contextmanager
        def cursor(self):
            with conn.cursor() as cursor:

                class CapturedCursor:
                    def execute(self, query, params=None):
                        captured.query, captured.params = query, params
                        if captured.reference:
                            if "latest_options AS" in query:
                                query = "WITH " + query[query.index("latest_options AS") :]
                                query = query.replace(
                                    "evaluation_prediction_rows mp",
                                    "model_prediction_latest_rows mp",
                                )
                            else:
                                query = query.replace(
                                    feature_importance._LATEST_PREDICTIONS_CTE, original_scope
                                )
                        cursor.execute(query, params)

                    def fetchall(self):
                        captured.rows = cursor.fetchall()
                        return captured.rows

                yield CapturedCursor()

    captured = CapturedConnection()
    monkeypatch.setattr(analyze_prediction_errors, "get_db", lambda: nullcontext(captured))

    def capture_writes(_connection, errors):
        writes.extend(copy.deepcopy(errors))
        return len(errors)

    monkeypatch.setattr(analyze_prediction_errors, "create_error_analyses_batch", capture_writes)

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    measurements = []
    for kind, read in (
        ("errors", analyze_prediction_errors.run),
        ("calibration_named", lambda: feature_importance.get_calibration_data(captured, "same")),
        ("calibration_all", lambda: feature_importance.get_calibration_data(captured)),
        ("combos", lambda: feature_importance.recommend_best_combos(captured, min_samples=1)),
    ):
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE fqp")
            cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
            assert cursor.fetchone() == (False,)
        captured.reference = False
        writes.clear()
        actual = read()
        query, params = captured.query, captured.params
        actual_rows, actual_writes = captured.rows, copy.deepcopy(writes)
        captured.reference = True
        writes.clear()
        expected = read()
        assert actual == expected
        assert actual_writes == writes
        assert sorted(actual_rows) == sorted(captured.rows)
        assert actual_rows
        if kind == "errors":
            picks = {row[1]: row for row in actual_rows if row[1] > 100}
            assert set(picks) == {101, 105, 106, 107, 108, 114}
            assert picks[106][4] == "0" and picks[106][2] == 2
            assert picks[107][4] == "3" and picks[107][2] == 1
            assert picks[108][4] == "1" and picks[108][2] == 2
            assert actual["analyzed"] == 206
            assert actual["errors_found"] == 204
            reference_query = "WITH " + query[query.index("latest_options AS") :]
            reference_query = reference_query.replace(
                "evaluation_prediction_rows mp", "model_prediction_latest_rows mp"
            )
        else:
            reference_query = query.replace(
                feature_importance._LATEST_PREDICTIONS_CTE, original_scope
            )
        with conn.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + reference_query, params)
            reference_plan = cursor.fetchone()[0][0]
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + query, params)
            plan = cursor.fetchone()[0][0]
        measurements.append(
            {
                "kind": kind,
                "archive_rows": 900 * archive_snapshots,
                "original_prediction_node_work": prediction_work(reference_plan["Plan"]),
                "original_execution_ms": reference_plan["Execution Time"],
                "prediction_node_work": prediction_work(plan["Plan"]),
                "execution_ms": plan["Execution Time"],
            }
        )
    print(json.dumps({"evaluation_reads": measurements}), flush=True)
    # No settled results must yield empty reports rather than stale samples or
    # synthetic errors, even when historical predictions remain in the table.
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM official_results")
        cursor.execute("SET LOCAL ROLE fqp")
    captured.reference = False
    writes.clear()
    assert analyze_prediction_errors.run()["analyzed"] == 0
    assert writes == []
    assert feature_importance.get_calibration_data(captured, "same")["n_predictions"] == 0
    assert feature_importance.get_calibration_data(captured)["n_predictions"] == 0
    assert feature_importance.recommend_best_combos(captured, min_samples=1) == []
    assert all(measurement["prediction_node_work"] < 15000 for measurement in measurements)


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_calibration_training_and_display_exclude_unusable_results_without_blocking(
    isolated_database, archive_snapshots, monkeypatch
):
    from psycopg2 import sql

    from scripts import feature_importance
    from scripts.jobs import train_probability_calibration as training
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("SET jit=off")
        cursor.execute(
            (Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql").read_text()
        )
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same'),('other')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-08-01 18:00'::timestamp FROM generate_series(1,134)""")
        cursor.execute("UPDATE official_matches SET kickoff_time=NULL WHERE id=130")
        cursor.execute("""INSERT INTO official_results
            (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            SELECT id,'confirmed','3',2,0 FROM official_matches WHERE id<=100""")
        results = {match_id: [match_id, "final", "3", 2, 0] for match_id in range(101, 135)}
        results[102][1:] = ["confirmed", "1", 1, 1]
        results[103][1:] = ["confirmed", "0", 0, 1]
        for match_id, status in ((104, "pending"), (105, "provisional"), (106, "cancelled")):
            results[match_id][1] = status
        results[107][3] = None
        results[108][4] = None
        results[109][3:] = [None, None]
        results[110][3] = -1
        results[111][4] = -1
        results[112][2] = "1"  # Confirmed SPF contradicts the full-time score.
        results[113][2] = "void"
        results[114][2] = None  # Complete score can supply a missing SPF code.
        results[115][2] = ""
        results[132][2:] = [None, 0, 0]
        results[133][3:] = [-1, -1]
        results[134][2] = "h"
        cursor.executemany(
            """INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals)
                VALUES (%s,%s,%s,%s,%s)""",
            [row for match_id, row in results.items() if match_id != 125],
        )
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute',
                   'spf',o,CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            SELECT m.id,1,'2026-07-29'::timestamp+m.id*INTERVAL '1 minute',
                   CASE WHEN m.id=123 THEN 'rqspf' ELSE 'spf' END,o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   CASE WHEN m.id=129 THEN 'invalid' ELSE 'valid' END,
                   CASE WHEN m.id=116 THEN '{"model_independent":false}'::jsonb
                        WHEN m.id=117 THEN '{}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o WHERE m.id>100""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            SELECT m.id,2,CASE WHEN m.id=119 THEN '2026-08-02'::timestamp
                              WHEN m.id=122 THEN '2026-07-29'::timestamp
                                                +m.id*INTERVAL '1 minute'
                              ELSE '2026-07-30'::timestamp END,'spf',o,
                   CASE WHEN m.id=121 THEN NULL WHEN o='1' THEN 0.6 ELSE 0.2 END,
                   CASE WHEN m.id=118 THEN 'invalid' ELSE 'valid' END,
                   CASE WHEN m.id=120 THEN '{"model_independent":false}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id IN (118,119,120,121,122) AND (m.id<>121 OR o='3')""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            VALUES (124,1,'2026-07-30','spf','unknown',0.9,'valid',
                    '{"model_independent":true}')""")
    conn.commit()

    for match_id, completed in ((126, True), (127, False), (128, True)):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="calibration-integrity-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": 2}],
            input_manifest={"match_ids": [match_id]},
            provenance_status="incomplete",
        )
        metadata = {
            "match_id": match_id,
            "model_version_id": 2,
            "play_type": "spf",
            "predict_time": "2026-08-02T12:00:00" if match_id == 128 else "2026-07-28T12:00:00",
            "feature_snapshot_id": 77,
            "expected_options": ["3", "1", "0"],
        }
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata=metadata,
            predictions=[
                {
                    **{key: value for key, value in metadata.items() if key != "expected_options"},
                    "option_code": option,
                    "model_probability": probability,
                    "market_probability": probability,
                    "validation_status": "valid",
                    "calculation_version": "calibration-fixture",
                    "odds_snapshot_id": 30,
                    "break_even_probability": probability,
                    "market_edge": 0,
                    "breakeven_edge": 0,
                    "ev": 0,
                    "uncertainty_reason": {"model_independent": True},
                }
                for option, probability in (("3", 0.1), ("1", 0.2), ("0", 0.7))
            ],
        )
        if completed:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": 1,
                    "completed_groups": 1,
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()

    # Explicit known labels/probabilities, independent of the production SQL.
    probabilities = {"3": 0.7, "1": 0.2, "0": 0.1}
    expected = [
        (model, match_id, option, probability, "3")
        for model in ("same", "other")
        for match_id in range(1, 101)
        for option, probability in probabilities.items()
    ]
    for match_id in (101, 102, 103, 114, 121, 122, 124, 126, 127, 131, 132):
        actual = "1" if match_id in (102, 132) else "0" if match_id == 103 else "3"
        selected = (
            {"3": 0.2, "1": 0.6, "0": 0.2}
            if match_id == 122
            else {"3": 0.1, "1": 0.2, "0": 0.7}
            if match_id == 126
            else probabilities
        )
        expected.extend(
            ("same", match_id, option, probability, actual)
            for option, probability in selected.items()
            if match_id != 121 or option != "3"
        )

    class CapturedConnection:
        query = ""
        params = None
        rows = None

        @contextmanager
        def cursor(self):
            with conn.cursor() as cursor:

                class CapturedCursor:
                    def execute(self, query, params=None):
                        captured.query, captured.params = query, params
                        cursor.execute(query, params)

                    def fetchall(self):
                        captured.rows = cursor.fetchall()
                        return captured.rows

                yield CapturedCursor()

    captured = CapturedConnection()
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == (False,)
    rows = training._load_settled_prediction_rows(captured)
    training_query = captured.query
    actual = [(row[0], row[1], row[2], float(row[3]), row[4]) for row in rows]
    assert sorted(actual) == sorted(expected)
    assert [row[:3] for row in rows] == [
        row[:3] for row in sorted(rows, key=lambda row: (row[0], row[5], row[1], row[2]))
    ]

    plans = []
    for model in ("same", None):
        result = feature_importance.get_calibration_data(captured, model, n_bins=10)
        expected_pairs = [
            (row[3], int(row[2] == row[4])) for row in expected if model is None or row[0] == model
        ]
        assert sorted((float(p), int(correct)) for p, correct in captured.rows) == sorted(
            expected_pairs
        )
        assert result["status"] == "ok"
        assert result["model_name"] == (model or "all")
        assert result["n_predictions"] == len(expected_pairs)
        assert sum(bin_["count"] for bin_ in result["bins"]) == len(expected_pairs)
        assert sum(bin_["actual_freq"] * bin_["count"] for bin_ in result["bins"]) == pytest.approx(
            sum(correct for _, correct in expected_pairs), abs=0.1
        )
        plans.append((model or "all", captured.query, captured.params))
    plans.append(("training", training_query, None))

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    measurements = []
    for kind, query, params in plans:
        with conn.cursor() as cursor:
            cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + query, params)
            plan = cursor.fetchone()[0][0]
        work = prediction_work(plan["Plan"])
        measurements.append(
            {
                "kind": kind,
                "archive_rows": 900 * archive_snapshots,
                "prediction_node_work": work,
                "execution_ms": plan["Execution Time"],
            }
        )
        assert work < 15000
    print(json.dumps({"calibration_integrity_reads": measurements}), flush=True)

    # The real dry-run path succeeds with no usable results and stores nothing.
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE official_results SET result_status='pending'")
        cursor.execute("SET LOCAL ROLE fqp")
    monkeypatch.setattr(training, "get_db", lambda: nullcontext(captured))
    empty = training._run_impl(dry_run=True)
    assert empty["status"] == "ok"
    assert empty["settled_prediction_rows"] == empty["profiles"] == empty["stored"] == 0
    for model in ("same", None):
        result = feature_importance.get_calibration_data(captured, model)
        assert result["n_predictions"] == 0
        assert result["bins"] == []


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_evaluation_job_stores_only_consistent_complete_results_and_retries_without_duplicates(
    isolated_database, archive_snapshots, monkeypatch, request
):
    from psycopg2 import sql

    from scripts import evaluation_metrics
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database

    def reset_role():
        conn.rollback()
        with conn.cursor() as cursor:
            cursor.execute("RESET ROLE")
        conn.commit()

    request.addfinalizer(reset_role)
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("SET jit=off")
        migrations = Path(__file__).resolve().parents[2] / "sql"
        cursor.execute((migrations / "113_prediction_read_paths.sql").read_text())
        metrics_ddl = re.search(
            r"CREATE TABLE IF NOT EXISTS market_efficiency_metrics \(.*?\n\);",
            (migrations / "03_model_research_schema.sql").read_text(),
            re.S,
        )
        assert metrics_ddl is not None
        cursor.execute(metrics_ddl.group())
        cursor.execute("ALTER TABLE official_matches ADD COLUMN sale_stop_time TIMESTAMP")
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same'),('other')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time,business_date,match_status)
            SELECT '2026-08-01 18:00'::timestamp,'2026-08-01'::date,'Settled'
            FROM generate_series(1,132)""")
        cursor.execute("UPDATE official_matches SET match_status='Scheduled' WHERE id=129")
        cursor.execute("UPDATE official_matches SET kickoff_time=NULL WHERE id=130")
        cursor.execute("""INSERT INTO official_results
            (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            SELECT id,'confirmed','3',2,0 FROM official_matches WHERE id<=100""")
        results = {match_id: [match_id, "final", "3", 2, 0] for match_id in range(101, 133)}
        results[102][1:] = ["confirmed", "1", 1, 1]
        results[103][1:] = ["confirmed", "0", 0, 1]
        for match_id, status in ((104, "pending"), (105, "provisional"), (106, "cancelled")):
            results[match_id][1] = status
        results[107][3] = None
        results[108][4] = None
        results[109][3:] = [None, None]
        results[110][3] = -1
        results[111][4] = -1
        results[112][2] = "1"
        results[113][2] = "void"
        results[114][2] = None
        results[115][2] = ""
        cursor.executemany(
            """INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals)
                VALUES (%s,%s,%s,%s,%s)""",
            [row for match_id, row in results.items() if match_id != 125],
        )
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,validation_status,uncertainty_reason)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute','spf',o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   CASE WHEN o='3' THEN 0.4 WHEN o='1' THEN 0.35 ELSE 0.25 END,
                   'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,validation_status,uncertainty_reason)
            SELECT m.id,1,'2026-07-29'::timestamp,'spf',o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   CASE WHEN o='3' THEN 0.4 WHEN o='1' THEN 0.35 ELSE 0.25 END,'valid',
                   CASE WHEN m.id=116 THEN '{"model_independent":false}'::jsonb
                        WHEN m.id=117 THEN '{}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o WHERE m.id>100""")
        cursor.execute("UPDATE model_predictions SET play_type='rqspf' WHERE match_id=123")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,validation_status,uncertainty_reason)
            SELECT m.id,CASE WHEN m.id=122 THEN 2 ELSE 1 END,
                   CASE WHEN m.id=119 THEN '2026-08-02'::timestamp
                        WHEN m.id=122 THEN '2026-07-29'::timestamp
                        ELSE '2026-07-30'::timestamp END,'spf',o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   CASE WHEN o='3' THEN 0.4 WHEN o='1' THEN 0.35 ELSE 0.25 END,
                   CASE WHEN m.id=118 THEN 'invalid' ELSE 'valid' END,
                   CASE WHEN m.id=120 THEN '{"model_independent":false}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches m CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id IN (118,119,120,121,122) AND (m.id<>121 OR o='3')""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,validation_status,uncertainty_reason)
            VALUES (124,1,'2026-07-29','spf','unknown',0.9,0.9,'valid',
                    '{"model_independent":true}')""")
        cursor.execute("""INSERT INTO official_odds_snapshots
                (match_id,play_type,option_code,sp_value,snapshot_time)
            SELECT m.id,'spf',o,CASE WHEN o='h' THEN 2 WHEN o='d' THEN 3 ELSE 6 END,
                   '2026-08-01 17:00'::timestamp
            FROM official_matches m CROSS JOIN unnest(ARRAY['h','d','a']) o WHERE m.id<>132""")
        cursor.execute("""INSERT INTO market_efficiency_metrics
                (match_id,model_version_id,snapshot_time,play_type,option_code,
                 brier_score,clv_score) VALUES (131,1,'2026-07-29','spf','3',0.77,0.02)""")
    conn.commit()

    for match_id, completed in ((126, True), (127, False), (128, True)):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="evaluation-truth-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": 2}],
            input_manifest={"match_ids": [match_id]},
            provenance_status="incomplete",
        )
        metadata = {
            "match_id": match_id,
            "model_version_id": 2,
            "play_type": "spf",
            "predict_time": "2026-08-02T12:00:00" if match_id == 128 else "2026-07-28T12:00:00",
            "feature_snapshot_id": 77,
            "expected_options": ["3", "1", "0"],
        }
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata=metadata,
            predictions=[
                {
                    **{key: value for key, value in metadata.items() if key != "expected_options"},
                    "option_code": option,
                    "model_probability": probability,
                    "market_probability": {"3": 0.4, "1": 0.35, "0": 0.25}[option],
                    "validation_status": "valid",
                    "calculation_version": "evaluation-fixture",
                    "odds_snapshot_id": 30,
                    "break_even_probability": probability,
                    "market_edge": 0,
                    "breakeven_edge": 0,
                    "ev": 0,
                    "uncertainty_reason": {"model_independent": True},
                }
                for option, probability in (("3", 0.1), ("1", 0.2), ("0", 0.7))
            ],
        )
        if completed:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": 1,
                    "completed_groups": 1,
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
        cursor.execute("GRANT INSERT,UPDATE ON market_efficiency_metrics TO fqp")
        cursor.execute("GRANT USAGE ON SEQUENCE market_efficiency_metrics_id_seq TO fqp")
        cursor.execute("SET ROLE fqp")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == (False,)
    conn.commit()

    class CapturedConnection:
        query = ""
        parameters = None

        def cursor(self):
            cursor = conn.cursor()

            class CapturedCursor:
                def execute(self, query, parameters=None):
                    if "closing_odds AS" in query:
                        captured.query, captured.parameters = query, parameters
                    cursor.execute(query, parameters)

                def fetchall(self):
                    return cursor.fetchall()

                def fetchone(self):
                    return cursor.fetchone()

                def __enter__(self):
                    return self

                def __exit__(self, *_args):
                    cursor.close()

            return CapturedCursor()

        def commit(self):
            conn.commit()

    captured = CapturedConnection()
    monkeypatch.setattr("apps.backend.src.db.get_db", lambda: nullcontext(captured))
    result = evaluation_metrics.run()
    with conn.cursor() as cursor:
        cursor.execute("""SELECT match_id,model_version_id,option_code,brier_score,
                                 log_loss,rps,clv_score FROM market_efficiency_metrics
                          ORDER BY match_id,model_version_id""")
        stored = cursor.fetchall()
    # Explicit expected match/version truth, independent of the production SQL.
    expected = {(match_id, version): "3" for match_id in range(1, 101) for version in (2, 3)}
    for match_id in (101, 102, 103, 114, 122, 124, 126, 127, 132):
        expected[(match_id, 2 if match_id in (122, 126) else 1)] = (
            "1" if match_id == 102 else "0" if match_id == 103 else "3"
        )
    assert {(row[0], row[1]) for row in stored} == set(expected) | {(131, 1)}
    assert result["status"] == "ok"
    assert result["evaluated"] == result["stored"] == len(expected)
    assert result["model_count"] == 2
    for match_id, version, selected, bs, ll, rps, move in stored:
        if match_id == 131:
            assert float(bs) == 0.77 and float(move) == 0.02
            continue
        truth = expected[(match_id, version)]
        probabilities = (
            {"3": 0.1, "1": 0.2, "0": 0.7} if match_id == 126 else {"3": 0.7, "1": 0.2, "0": 0.1}
        )
        expected_bs = sum(
            (probability - int(option == truth)) ** 2
            for option, probability in probabilities.items()
        )
        assert float(bs) == pytest.approx(expected_bs, abs=1e-6)
        assert float(ll) > 0 and float(rps) >= 0
        assert selected == ("0" if match_id == 126 else "3")
        if match_id == 132:
            assert move is None
        else:
            assert float(move) == pytest.approx(-1 / 12 if match_id == 126 else 0.1, abs=1e-6)

    # Remove only newly generated rows so EXPLAIN measures the same pending scope.
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("DELETE FROM market_efficiency_metrics WHERE match_id<>131")
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + captured.query, captured.parameters)
        plan = cursor.fetchone()[0][0]

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    work = prediction_work(plan["Plan"])
    print(
        json.dumps(
            {
                "evaluation_truth_reads": {
                    "archive_rows": 900 * archive_snapshots,
                    "prediction_node_work": work,
                    "execution_ms": plan["Execution Time"],
                }
            }
        ),
        flush=True,
    )
    assert work < 15000
    conn.rollback()
    second = evaluation_metrics.run()
    assert second["evaluated"] == second["stored"] == 1  # NULL CLV may be updated, not duplicated.
    with conn.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM market_efficiency_metrics")
        assert cursor.fetchone()[0] == len(expected) + 1
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("RESET ROLE")
        cursor.execute("UPDATE official_results SET result_status='pending'")
        cursor.execute("SET LOCAL ROLE fqp")
    assert evaluation_metrics.run()["evaluated"] == 0


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_backtest_uses_consistent_spf_truth_without_changing_other_play_results(
    isolated_database, archive_snapshots
):
    from psycopg2 import sql

    from scripts.backtest_engine import BacktestConfig, BacktestEngine
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("SET jit=off")
        cursor.execute(
            (Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql").read_text()
        )
        cursor.execute("""ALTER TABLE official_results ADD COLUMN rqspf_result TEXT,
            ADD COLUMN total_goals_result TEXT, ADD COLUMN score_result TEXT,
            ADD COLUMN half_full_result TEXT""")
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same'),('other')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time,business_date,match_status)
            SELECT '2026-08-01 18:00'::timestamp,'2026-08-01'::date,'Settled'
            FROM generate_series(1,133)""")
        cursor.execute("UPDATE official_matches SET match_status='Scheduled' WHERE id=129")
        cursor.execute("UPDATE official_matches SET kickoff_time=NULL WHERE id=130")
        cursor.execute("""INSERT INTO official_results
            (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            SELECT id,'confirmed','3',2,0 FROM official_matches WHERE id<=100""")
        results = {match_id: [match_id, "final", "3", 2, 0] for match_id in range(101, 134)}
        results[102][1:] = ["confirmed", "1", 1, 1]
        results[103][1:] = ["confirmed", "0", 0, 1]
        for match_id, status in ((104, "pending"), (105, "provisional"), (106, "cancelled")):
            results[match_id][1] = status
        results[107][3] = None
        results[108][4] = None
        results[109][3:] = [None, None]
        results[110][3] = -1
        results[111][4] = -1
        results[112][2] = "1"
        results[113][2] = "void"
        results[114][2:] = [None, 0, 0]
        results[115][2] = ""
        cursor.executemany(
            """INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals)
                VALUES (%s,%s,%s,%s,%s)""",
            [row for match_id, row in results.items() if match_id != 125],
        )
        # Other plays have their own truth. A contradictory SPF cannot decide
        # a handicap, total, correct score or half/full bet.
        cursor.execute("""UPDATE official_results SET rqspf_result='1',
            total_goals_result='2',score_result='20',half_full_result='1-3'""")
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,validation_status,uncertainty_reason)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute','spf',o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   0.3,0.1,'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT id,1,'2026-07-29','spf',o,
                   CASE WHEN o='3' THEN 0.7 WHEN o='1' THEN 0.2 ELSE 0.1 END,
                   0.3,0.1,0.8,'valid',
                   CASE WHEN id=116 THEN '{"model_independent":false}'::jsonb
                        WHEN id=117 THEN '{}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o WHERE id>100""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT id,CASE WHEN id=122 THEN 2 ELSE 1 END,
                   CASE WHEN id=119 THEN '2026-08-02'::timestamp
                        WHEN id=122 THEN '2026-07-29'::timestamp
                        ELSE '2026-07-30'::timestamp END,'spf',o,
                   CASE WHEN id=122 THEN CASE o WHEN '3' THEN 0.6 WHEN '1' THEN 0.3 ELSE 0.1 END
                        ELSE 0.6 END,
                   0.3,0.1,0.8,CASE WHEN id=118 THEN 'invalid' ELSE 'valid' END,
                   CASE WHEN id=120 THEN '{"model_independent":false}'::jsonb
                        ELSE '{"model_independent":true}'::jsonb END
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE id IN (118,119,120,121,122) AND (id<>121 OR o='3')""")
        cursor.execute("UPDATE model_predictions SET model_probability=0 WHERE match_id=132")
        cursor.execute("UPDATE model_predictions SET model_probability=NULL WHERE match_id=133")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT m.id,1,'2026-07-29',p.play,p.option_code,0.7,0.3,0.1,0.8,
                   'valid','{"model_independent":true}'
            FROM official_matches m CROSS JOIN (VALUES
                ('rqspf','1'),('zjq','2'),('total_goals','2'),('bf','20'),
                ('score','20'),('bqc','13'),('half_full','13')) p(play,option_code)
            WHERE m.id IN (101,104,107,108,110,111,112,113,114,115)""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,validation_status,uncertainty_reason)
            VALUES (124,1,'2026-07-29','spf','unknown',0.9,0.3,0.9,'valid',
                    '{"model_independent":true}')""")
        cursor.execute("""INSERT INTO official_odds_snapshots
                (match_id,play_type,option_code,sp_value,snapshot_time)
            SELECT m.id,p.play,p.option_code,s.value,s.at_time
            FROM official_matches m CROSS JOIN (VALUES
                ('spf','h'),('spf','d'),('spf','a'),('rqspf','d'),('zjq','2'),
                ('total_goals','2'),('bf','20'),('score','20'),('bqc','13'),('half_full','13')
            ) p(play,option_code) CROSS JOIN (VALUES
                (2.0,'2025-12-30'::timestamp), (2.5,'2025-12-31'::timestamp),
                (2.0,'2026-07-27'::timestamp), (2.5,'2026-07-28'::timestamp),
                (9.0,'2026-07-31'::timestamp)) s(value,at_time)
            WHERE m.id<>131""")
    conn.commit()

    for match_id, completed in ((126, True), (127, False), (128, True)):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="backtest-truth-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": 2}],
            input_manifest={"match_ids": [match_id]},
            provenance_status="incomplete",
        )
        metadata = {
            "match_id": match_id,
            "model_version_id": 2,
            "play_type": "spf",
            "predict_time": "2026-08-02T12:00:00" if match_id == 128 else "2026-07-28T12:00:00",
            "feature_snapshot_id": 77,
            "expected_options": ["3", "1", "0"],
        }
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata=metadata,
            predictions=[
                {
                    **{key: value for key, value in metadata.items() if key != "expected_options"},
                    "option_code": option,
                    "model_probability": probability,
                    "market_probability": 0.3,
                    "validation_status": "valid",
                    "calculation_version": "backtest-fixture",
                    "odds_snapshot_id": 30,
                    "break_even_probability": probability,
                    "market_edge": 0,
                    "breakeven_edge": 0,
                    "ev": 0.1,
                    "uncertainty_reason": {"model_independent": True},
                }
                for option, probability in (("3", 0.1), ("1", 0.2), ("0", 0.7))
            ],
        )
        if completed:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": 1,
                    "completed_groups": 1,
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == (False,)
    engine = BacktestEngine(
        conn, BacktestConfig(walk_forward=False, signal_strength="all", min_model_prob=0.01)
    )
    rows = engine.load_data()
    expected = {
        (match_id, version, "spf", option): "3"
        for match_id in range(1, 101)
        for version in (2, 3)
        for option in ("3", "1", "0")
    }
    for match_id in (101, 102, 103, 114, 121, 122, 123, 124, 126, 127, 131):
        version = 2 if match_id in (122, 126) else 1
        truth = "1" if match_id in (102, 114) else "0" if match_id == 103 else "3"
        for option in ("3",) if match_id == 121 else ("3", "1", "0"):
            expected[(match_id, version, "spf", option)] = truth
    other_results = {
        "rqspf": "1",
        "zjq": "2",
        "total_goals": "2",
        "bf": "20",
        "score": "20",
        "bqc": "13",
        "half_full": "13",
    }
    for match_id in (101, 112, 113, 114, 115):
        for play, truth in other_results.items():
            expected[(match_id, 1, play, truth)] = truth
    # Keep the existing public row shape (model name, no version column).
    expected_by_name = {
        (match_id, "other" if version == 3 else "same", play, option): truth
        for (match_id, version, play, option), truth in expected.items()
    }
    actual = {
        (row["match_id"], row["model_name"], row["play_type"], row["option_code"]): row[
            "actual_result"
        ]
        for row in rows
    }
    assert actual == expected_by_name
    assert len(rows) == len(expected_by_name)
    assert {
        row["option_code"]: float(row["model_probability"])
        for row in rows
        if row["match_id"] == 122
    } == {"3": 0.6, "1": 0.3, "0": 0.1}
    assert all(float(row["sp_value"]) == (0 if row["match_id"] == 131 else 2.5) for row in rows)
    bets = engine._simulate_bets(rows, "2026-08-01", "2026-08-01")
    assert len(bets) == 245
    assert sum(bet.profit for bet in bets) == pytest.approx(357.5)
    assert next(bet for bet in bets if bet.match_id == 126).option_code == "0"
    result = engine.run()
    assert result["status"] == "ok" and result["total_bets"] == len(bets)
    assert sum(metrics["total_profit"] for metrics in result["aggregate"].values()) == 357.5

    query, parameters = engine._build_query()
    with conn.cursor() as cursor:
        # Compare only the read boundary against the canonical original view;
        # eligibility and the repaired result rules stay identical.
        from scripts.model_evaluation_scope import EVALUATION_PREDICTION_ROWS_CTES

        oracle = query.replace(EVALUATION_PREDICTION_ROWS_CTES, "WITH ", 1).replace(
            "FROM evaluation_prediction_rows source_mp",
            "FROM model_prediction_latest_rows source_mp",
        )
        oracle = re.sub(r"\bWITH\s*,", "WITH ", oracle, count=1)
        cursor.execute(oracle, parameters)
        assert sorted(cursor.fetchall(), key=repr) == sorted(
            [tuple(row[column[0]] for column in cursor.description) for row in rows], key=repr
        )
        cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + query, parameters)
        plan = cursor.fetchone()[0][0]

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    work = prediction_work(plan["Plan"])
    print(
        json.dumps(
            {
                "backtest_truth_reads": {
                    "archive_rows": 900 * archive_snapshots,
                    "prediction_node_work": work,
                    "execution_ms": plan["Execution Time"],
                }
            }
        ),
        flush=True,
    )
    assert work < 15000
    filtered = BacktestEngine(
        conn,
        BacktestConfig(
            time_start="2026-08-01",
            time_end="2026-08-01",
            play_types=["rqspf"],
            model_names=["same"],
            model_ids=[1],
            confidence_min=0.5,
        ),
    ).load_data()
    assert {row["match_id"] for row in filtered} == {101, 112, 113, 114, 115}
    assert BacktestEngine(conn, BacktestConfig(time_start="2026-08-02")).load_data() == []
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE official_results SET result_status='pending'")
        cursor.execute("SET LOCAL ROLE fqp")
    assert engine.run()["status"] == "no_data"


@pytest.mark.parametrize("valid_matches", [90, 120, 5005])
def test_explanation_training_uses_only_trustworthy_results_and_eligible_snapshots(
    isolated_database, monkeypatch, valid_matches
):
    import numpy as np
    from psycopg2 import sql

    from scripts import feature_importance
    from scripts.feature_schema import CURRENT_SNAPSHOT_VERSION, FEATURE_COLUMNS

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='15s'")
        cursor.execute("CREATE TABLE competition_seasons(id BIGINT PRIMARY KEY)")
        cursor.execute("CREATE TABLE stadiums(id BIGINT PRIMARY KEY)")
        cursor.execute("CREATE TABLE simulation_ticket_items(id BIGINT PRIMARY KEY)")
        migrations = Path(__file__).resolve().parents[2] / "sql"
        cursor.execute((migrations / "12_match_feature_snapshots.sql").read_text())
        cursor.execute((migrations / "71_upset_risk_feature_schema.sql").read_text())
        cursor.execute("ALTER TABLE official_matches ADD COLUMN league_name TEXT")
        cursor.execute("INSERT INTO teams(team_name_cn) VALUES ('home'),('away')")
        cursor.execute(
            """INSERT INTO official_matches(business_date,kickoff_time,match_status,league_name)
            SELECT '2026-08-01'::date,'2026-08-01 18:00'::timestamp,'Settled','fixture'
            FROM generate_series(1,%s)""",
            (valid_matches + 24,),
        )
        cursor.execute(
            """INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            SELECT id,'confirmed',CASE id%%3 WHEN 0 THEN '0' WHEN 1 THEN '1' ELSE '3' END,
                   CASE id%%3 WHEN 0 THEN 0 WHEN 1 THEN 1 ELSE 2 END,
                   CASE id%%3 WHEN 0 THEN 2 WHEN 1 THEN 1 ELSE 0 END
            FROM official_matches WHERE id<=%s""",
            (valid_matches,),
        )
        results = {index: [valid_matches + index, "final", "3", 2, 0] for index in range(1, 25)}
        results[2][1:] = ["confirmed", "1", 1, 1]
        results[3][1:] = ["confirmed", "0", 0, 1]
        for index, status in ((4, "pending"), (5, "provisional"), (6, "cancelled")):
            results[index][1] = status
        results[7][3] = None
        results[8][4] = None
        results[9][3:] = [None, None]
        results[10][3] = -1
        results[11][4] = -1
        results[12][2] = "1"
        results[13][2] = "void"
        results[14][2:] = [None, 0, 0]
        results[15][2] = ""
        cursor.executemany(
            """INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            VALUES (%s,%s,%s,%s,%s)""",
            [row for index, row in results.items() if index != 20],
        )
        cursor.execute(
            """UPDATE official_matches SET kickoff_time=NULL WHERE id=%s""",
            (valid_matches + 19,),
        )
        cursor.execute(
            "UPDATE official_matches SET match_status='Scheduled' WHERE id=%s",
            (valid_matches + 24,),
        )
        # Bad labels are newer than the valid business dates: filtering must
        # happen before LIMIT, so they cannot consume the 5000-match budget.
        cursor.execute(
            "UPDATE official_matches SET business_date='2026-08-02' WHERE id=ANY(%s)",
            ([valid_matches + index for index in (7, 8, 9, 10, 11, 12, 13, 15)],),
        )
        cursor.execute(
            """INSERT INTO match_feature_snapshots
                (match_id,snapshot_time,feature_version,home_team_id,away_team_id,
                 home_attack_strength_score,home_lineup_confirmed,temperature_2m,precipitation)
            SELECT id,'2026-07-30',%s,1,2,id::numeric/100,false,
                   CASE WHEN id%%2=0 THEN 20 ELSE NULL END,0
            FROM official_matches WHERE id<>%s""",
            (CURRENT_SNAPSHOT_VERSION, valid_matches + 23),
        )
        cursor.execute(
            "UPDATE match_feature_snapshots SET feature_version='v4_observed_form' WHERE match_id=%s",
            (valid_matches + 16,),
        )
        cursor.execute(
            "UPDATE match_feature_snapshots SET snapshot_time='2026-08-02' WHERE match_id=%s",
            (valid_matches + 17,),
        )
        cursor.execute(
            "UPDATE match_feature_snapshots SET snapshot_time='2026-08-01 18:00' WHERE match_id=%s",
            (valid_matches + 18,),
        )
        cursor.execute(
            """UPDATE match_feature_snapshots SET wind_speed_10m=99
            WHERE match_id=ANY(%s)""",
            ([valid_matches + index for index in (7, 8, 9, 10, 11, 12, 13, 15)],),
        )
        cursor.executemany(
            """INSERT INTO match_feature_snapshots
                (match_id,snapshot_time,feature_version,home_team_id,away_team_id,
                 home_attack_strength_score,home_lineup_confirmed,precipitation)
            VALUES (%s,%s,%s,1,2,%s,false,NULL)""",
            [
                (valid_matches + 21, "2026-07-30", CURRENT_SNAPSHOT_VERSION, 0),
                (valid_matches + 21, "2026-08-02", CURRENT_SNAPSHOT_VERSION, 999),
                (valid_matches + 22, "2026-07-31", "future-unsupported", 999),
            ],
        )
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == (False,)
    data = feature_importance._load_training_data(conn, min_samples=1)
    assert data is not None
    features, labels, match_ids, names = data
    expected_ids = sorted(
        [*range(1, valid_matches + 1), *[valid_matches + i for i in (1, 2, 3, 14, 21, 22, 24)]]
    )[:5000]
    assert match_ids == expected_ids
    expected_labels = [
        match_id % 3
        if match_id <= valid_matches
        else 1
        if match_id - valid_matches in (2, 14)
        else 0
        if match_id - valid_matches == 3
        else 2
        for match_id in expected_ids
    ]
    np.testing.assert_array_equal(labels, expected_labels)
    expected_names = [
        name
        for name in FEATURE_COLUMNS
        if name
        in (
            "home_attack_strength_score",
            "home_lineup_confirmed",
            "temperature_2m",
            "precipitation",
        )
    ]
    assert names == expected_names  # Excluded-only wind is not an observed feature.
    expected_features = [
        [
            0 if match_id == valid_matches + 21 else match_id / 100,
            0,
            np.nan if match_id == valid_matches + 21 or match_id % 2 else 20,
            np.nan if match_id == valid_matches + 21 else 0,
        ]
        for match_id in expected_ids
    ]
    np.testing.assert_allclose(features, expected_features, equal_nan=True)
    assert feature_importance._load_training_data(conn, min_samples=len(expected_ids) + 1) is None

    if valid_matches in (90, 120):
        # Exercise the real XGBoost fit at >=100 accepted matches. All model
        # state is restored by monkeypatch; no artifact/profile is persisted.
        for name, value in {
            "_trained_model": None,
            "_trained_explainer": None,
            "_explainer_initialized": False,
            "_feature_names_cache": [],
            "_importance_cache": {},
            "_train_score": 0.0,
        }.items():
            monkeypatch.setattr(feature_importance, name, value)
        trained = feature_importance.train_if_needed(conn, force=True)
        if valid_matches == 90:
            assert trained["status"] == "error" and "至少100场" in trained["error"]
            assert feature_importance._trained_model is None
        else:
            assert trained["status"] == "ok" and trained["n_samples"] == 127
            assert trained["n_features"] == len(names)
            assert trained["class_distribution"] == {
                "home_win": int((labels == 2).sum()),
                "draw": int((labels == 1).sum()),
                "away_win": int((labels == 0).sum()),
            }
            probabilities = feature_importance._trained_model.predict_proba(features[:3])
            assert probabilities.shape == (3, 3) and np.isfinite(probabilities).all()
            np.testing.assert_allclose(probabilities.sum(axis=1), 1, atol=1e-6)
    conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute("UPDATE official_results SET result_status='pending'")
        cursor.execute("SET LOCAL ROLE fqp")
    assert feature_importance._load_training_data(conn, min_samples=1) is None
    print(
        json.dumps(
            {
                "explanation_training_truth": {
                    "base_matches": valid_matches,
                    "admitted_matches": len(match_ids),
                    "feature_names": names,
                    "native_missing_values": int(np.isnan(features).sum()),
                    "real_fit": valid_matches == 120,
                }
            }
        ),
        flush=True,
    )


@pytest.mark.parametrize("consumer", ["evaluation", "backtest"])
def test_probability_inputs_cannot_abort_or_poison_other_matches(
    isolated_database, monkeypatch, consumer
):
    import math

    import psycopg2
    from psycopg2 import sql

    from scripts import evaluation_metrics
    from scripts.backtest_engine import BacktestConfig, BacktestEngine

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        migrations = Path(__file__).resolve().parents[2] / "sql"
        cursor.execute((migrations / "113_prediction_read_paths.sql").read_text())
        metrics_ddl = re.search(
            r"CREATE TABLE IF NOT EXISTS market_efficiency_metrics \(.*?\n\);",
            (migrations / "03_model_research_schema.sql").read_text(),
            re.S,
        )
        assert metrics_ddl is not None
        cursor.execute(metrics_ddl.group())
        cursor.execute("ALTER TABLE official_matches ADD COLUMN sale_stop_time TIMESTAMP")
        cursor.execute("""ALTER TABLE official_results ADD COLUMN rqspf_result TEXT,
            ADD COLUMN total_goals_result TEXT, ADD COLUMN score_result TEXT,
            ADD COLUMN half_full_result TEXT""")
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('probability-fixture')")
        cursor.execute("""INSERT INTO official_matches(business_date,kickoff_time,match_status)
            SELECT '2026-08-01'::date,'2026-08-01 18:00'::timestamp,'Settled'
            FROM generate_series(1,22)""")
        cursor.execute("""INSERT INTO official_results
            (match_id,result_status,spf_result,full_home_goals,full_away_goals)
            SELECT id,'final','3',2,0 FROM official_matches""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT id,1,'2026-07-29','spf',o,
                   CASE o WHEN '3' THEN 0.7 WHEN '1' THEN 0.2 ELSE 0.1 END,
                   CASE o WHEN '3' THEN 0.4 WHEN '1' THEN 0.35 ELSE 0.25 END,
                   CASE o WHEN '3' THEN 0.3 ELSE 0.1 END,0.8,
                   'valid','{"model_independent":true}'
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o""")
        for match_id, value in ((2, None), (3, -0.1), (4, 1.1), (5, "NaN")):
            cursor.execute(
                "UPDATE model_predictions SET model_probability=%s WHERE match_id=%s AND option_code='3'",
                (value, match_id),
            )
        cursor.execute("UPDATE model_predictions SET model_probability=0.7 WHERE match_id=6")
        cursor.execute("""UPDATE model_predictions SET model_probability=
            CASE option_code WHEN '3' THEN 1 ELSE 0 END WHERE match_id=7""")
        cursor.execute("UPDATE model_predictions SET model_probability=0 WHERE match_id=8")
        for match_id, value in ((9, None), (10, "NaN"), (11, -0.1), (12, 1.1)):
            cursor.execute(
                "UPDATE model_predictions SET market_probability=%s WHERE match_id=%s AND option_code='3'",
                (value, match_id),
            )
        cursor.execute("""UPDATE model_predictions SET market_probability=0.45
            WHERE match_id=13 AND option_code='0'""")
        cursor.execute("""UPDATE model_predictions SET market_probability=
            CASE option_code WHEN '3' THEN 0 WHEN '1' THEN 0.6 ELSE 0.4 END WHERE match_id=14""")
        cursor.execute("UPDATE model_predictions SET ev=NULL WHERE match_id=19")
        cursor.execute("UPDATE model_predictions SET ev='NaN' WHERE match_id=20")
        cursor.execute("UPDATE model_predictions SET ev=0 WHERE match_id=21")
        cursor.execute("UPDATE model_predictions SET market_probability=NULL WHERE match_id=22")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,validation_status,uncertainty_reason)
            SELECT id,1,'2026-07-30','spf',o,
                   CASE WHEN id=17 THEN 'NaN'::numeric
                        WHEN o='3' THEN 0.6 WHEN o='1' THEN 0.3 ELSE 0.1 END,
                   'NaN'::numeric,0.1,'valid','{"model_independent":true}'
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o WHERE id IN (17,18)""")
        cursor.execute("""INSERT INTO official_odds_snapshots
                (match_id,play_type,option_code,sp_value,snapshot_time)
            SELECT id,'spf',o,2,'2026-07-28'::timestamp
            FROM official_matches CROSS JOIN unnest(ARRAY['h','d','a']) o WHERE id<>16""")
        cursor.execute("""INSERT INTO official_odds_snapshots
                (match_id,play_type,option_code,sp_value,snapshot_time)
            SELECT id,'spf',o,CASE WHEN id=15 AND o='h' THEN 'NaN'::numeric ELSE 2.5 END,
                   '2026-08-01 17:00'::timestamp
            FROM official_matches CROSS JOIN unnest(ARRAY['h','d','a']) o WHERE id<>16""")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
        cursor.execute("GRANT INSERT,UPDATE ON market_efficiency_metrics TO fqp")
        cursor.execute("GRANT USAGE ON SEQUENCE market_efficiency_metrics_id_seq TO fqp")
    conn.commit()

    @contextmanager
    def runtime_database():
        with closing(psycopg2.connect(conn.dsn)) as runtime:
            with runtime.cursor() as cursor:
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cursor.execute("SET ROLE fqp")
                cursor.execute("SET statement_timeout='15s'")
                cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
                assert cursor.fetchone() == (False,)
            runtime.commit()
            yield runtime

    if consumer == "evaluation":
        monkeypatch.setattr("apps.backend.src.db.get_db", runtime_database)
        result = evaluation_metrics.run()
        assert result["evaluated"] == result["stored"] == 15
        expected = {1, 7, 9, 10, 11, 12, 13, 14, 15, 16, 18, 19, 20, 21, 22}
        with conn.cursor() as cursor:
            cursor.execute("""SELECT match_id,model_probability,market_probability,brier_score,
                log_loss,rps,clv_score,official_sp,ev FROM market_efficiency_metrics""")
            stored = {row[0]: row[1:] for row in cursor.fetchall()}
        assert set(stored) == expected
        for match_id, row in stored.items():
            probability, market, brier, ll, rps, move, odds, ev = row
            assert float(brier) == pytest.approx(
                0 if match_id == 7 else 0.26 if match_id == 18 else 0.14
            )
            assert all(value is None or math.isfinite(float(value)) for value in row)
            if match_id in (9, 10, 11, 12, 13, 18, 22):
                assert market is None and move is None
            if match_id in (15, 16):
                assert move is odds is ev is None
            if match_id == 14:
                assert market == 0 and float(move) == pytest.approx(1 / 3, abs=1e-6)
        assert float(stored[18][0]) == 0.6  # Latest missing market must not restore old prediction.
        assert evaluation_metrics.run()["stored"] == 9  # Existing NULL-CLV updates, no duplicates.
        with conn.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM market_efficiency_metrics")
            assert cursor.fetchone() == (15,)
    else:
        with runtime_database() as runtime:
            engine = BacktestEngine(
                runtime, BacktestConfig(walk_forward=False, signal_strength="all")
            )
            rows = engine.load_data()
            bets = engine._simulate_bets(rows, "2026-08-01", "2026-08-01")
            # Known malformed complete groups must not become sparse samples
            # after invalid/zero options or betting filters are removed.
            assert {bet.match_id for bet in bets} == {
                1,
                7,
                9,
                10,
                11,
                12,
                13,
                14,
                15,
                18,
                21,
                22,
            }
            assert len(bets) == 12 and sum(bet.profit for bet in bets) == 12
            for bet in bets:
                if bet.match_id in (9, 10, 11, 12, 13, 18, 22):
                    assert bet.market_prob is None
            assert next(bet for bet in bets if bet.match_id == 18).model_prob == 0.6
            result = engine.run()
            metrics = result["aggregate"]["probability-fixture"]
            assert metrics["total_profit"] == 12 and metrics["probability_edge"] is None
            json.dumps(result, allow_nan=False)
    json.dumps(result, allow_nan=False)
    print(json.dumps({"probability_input_consumer": consumer, "result": result}), flush=True)


@pytest.mark.parametrize("confidence_min", [None, 0.5])
def test_backtest_preserves_sparse_groups_without_mixing_or_hiding_bad_peers(
    isolated_database, confidence_min
):
    from psycopg2 import sql

    from scripts.backtest_engine import BacktestConfig, BacktestEngine

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='15s'")
        cursor.execute("SET jit=off")
        cursor.execute(
            (Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql").read_text()
        )
        cursor.execute("""ALTER TABLE official_results ADD COLUMN rqspf_result TEXT,
            ADD COLUMN total_goals_result TEXT, ADD COLUMN score_result TEXT,
            ADD COLUMN half_full_result TEXT""")
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('same'),('same')")
        cursor.execute("""INSERT INTO official_matches(business_date,kickoff_time,match_status)
            SELECT '2026-08-01'::date,'2026-08-01 18:00'::timestamp,'Settled'
            FROM generate_series(1,28)""")
        cursor.execute("""INSERT INTO official_results
                (match_id,result_status,spf_result,full_home_goals,full_away_goals,rqspf_result)
            SELECT id,'final','3',2,0,'1' FROM official_matches""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT id,1,'2026-07-29','spf',o,
                   CASE o WHEN '3' THEN 0.7 WHEN '1' THEN 0.2 ELSE 0.1 END,
                   CASE o WHEN '3' THEN 0.4 WHEN '1' THEN 0.35 ELSE 0.25 END,
                   CASE o WHEN '3' THEN 0.3 ELSE 0.1 END,0.8,
                   'valid','{"model_independent":true}'
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o""")
        cursor.execute("UPDATE model_predictions SET model_probability=0.7 WHERE match_id=2")
        for match_id, value in ((3, None), (4, "NaN"), (5, -0.1), (6, 1.1), (27, "NaN")):
            cursor.execute(
                """UPDATE model_predictions SET model_probability=%s
                    WHERE match_id=%s AND option_code='0'""",
                (value, match_id),
            )
        cursor.execute("""UPDATE model_predictions SET model_probability=
            CASE option_code WHEN '3' THEN 1 ELSE 0 END WHERE match_id=7""")
        cursor.execute("""DELETE FROM model_predictions WHERE
            (match_id IN (8,21) AND option_code<>'3') OR
            (match_id IN (9,10) AND option_code='0') OR match_id IN (16,26)""")
        cursor.execute("""UPDATE model_predictions SET model_probability=0.5
            WHERE match_id=10 AND option_code='1'""")
        cursor.execute("""UPDATE model_predictions SET model_probability=0.699
            WHERE match_id=11 AND option_code='3'""")
        cursor.execute("""UPDATE model_predictions SET market_probability=NULL
            WHERE match_id IN (12,28) AND option_code='0'""")
        cursor.execute("""UPDATE model_predictions SET market_probability=0.5
            WHERE match_id=13 AND option_code='0'""")
        cursor.execute("""UPDATE model_predictions SET ev=0.9
            WHERE match_id IN (14,15) AND option_code='0'""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            VALUES (14,2,'2026-07-30','spf','3',0.45,0.4,0.01,0.8,
                    'valid','{"model_independent":true}'),
                   (15,2,'2026-07-30','spf','3','NaN',0.4,0.01,0.8,
                    'valid','{"model_independent":true}'),
                   (16,1,'2026-07-29','spf','3',0.6,0.4,0.9,0.8,
                    'valid','{"model_independent":true}'),
                   (16,2,'2026-07-29','spf','1',0.4,0.35,0.1,0.8,
                    'valid','{"model_independent":true}')""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            SELECT id,CASE WHEN id=19 THEN 1 ELSE 2 END,'2026-07-30','spf',o,
                   CASE WHEN id IN (18,19) THEN 0.7
                        WHEN o='3' THEN 0.6 WHEN o='1' THEN 0.3 ELSE 0.1 END,
                   CASE o WHEN '3' THEN 0.4 WHEN '1' THEN 0.35 ELSE 0.25 END,
                   CASE o WHEN '3' THEN 0.3 ELSE 0.1 END,0.8,
                   'valid','{"model_independent":true}'
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE id IN (17,18,19)""")
        cursor.execute(
            "UPDATE model_predictions SET market_probability=0 WHERE match_id IN (20,21)"
        )
        cursor.execute("UPDATE model_predictions SET model_probability=0 WHERE match_id=22")
        cursor.execute("""UPDATE model_predictions SET model_probability=
            CASE WHEN match_id=23 THEN 0.705 ELSE 0.706 END
            WHERE match_id IN (23,24) AND option_code='3'""")
        cursor.execute("""INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,market_probability,ev,confidence_score,
                 validation_status,uncertainty_reason)
            VALUES (25,1,'2026-07-30','spf','unknown',0.9,0.4,0.9,0.8,
                    'valid','{"model_independent":true}'),
                   (26,1,'2026-07-29','rqspf','3',0.7,0.4,0.1,0.8,
                    'valid','{"model_independent":true}'),
                   (26,1,'2026-07-29','rqspf','1',0.7,0.35,0.3,0.8,
                    'valid','{"model_independent":true}')""")
        cursor.execute("""UPDATE model_predictions SET confidence_score=NULL,ev=NULL
            WHERE match_id IN (27,28) AND option_code='0'""")
        cursor.execute("""INSERT INTO official_odds_snapshots
                (match_id,play_type,option_code,sp_value,snapshot_time)
            SELECT id,p.play,o,2,'2026-07-28'::timestamp
            FROM official_matches CROSS JOIN unnest(ARRAY['h','d','a']) o
            CROSS JOIN (VALUES ('spf'),('rqspf')) p(play)""")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == (False,)
    engine = BacktestEngine(
        conn,
        BacktestConfig(
            walk_forward=False,
            signal_strength="all",
            min_model_prob=0.01,
            confidence_min=confidence_min,
        ),
    )
    rows = engine.load_data()
    expected_options = {
        1: "3",
        7: "3",
        8: "3",
        9: "3",
        11: "3",
        12: "3",
        13: "3",
        14: "3",
        16: "1",
        17: "3",
        20: "3",
        21: "3",
        23: "3",
        25: "3",
        26: "1",
        28: "3",
    }
    # No malformed complete group may be disguised as a sparse group by SQL
    # positivity/confidence or the later EV/odds/threshold filters.
    assert {row["match_id"] for row in rows} == set(expected_options)
    assert {row["option_code"] for row in rows if row["match_id"] == 14} == {"3"}
    assert {row["option_code"] for row in rows if row["match_id"] == 16} == {"1"}
    for row in rows:
        if row["match_id"] in (12, 13, 20, 28):
            assert row["market_probability"] is None
        if row["match_id"] == 21:
            assert row["market_probability"] == 0
    bets = engine._simulate_bets(rows, "2026-08-01", "2026-08-01")
    assert {bet.match_id: bet.option_code for bet in bets} == expected_options
    assert next(bet.model_prob for bet in bets if bet.match_id == 14) == 0.45
    assert next(bet.model_prob for bet in bets if bet.match_id == 17) == 0.6
    assert sum(bet.profit for bet in bets) == 14  # One draw selection loses; handicap draw wins.
    assert engine.compute_metrics(bets)["probability_edge"] is None
    result = engine.run()
    assert result["status"] == "ok" and result["total_bets"] == 16
    json.dumps(result, allow_nan=False)
    print(
        json.dumps(
            {
                "backtest_group_confidence_min": confidence_min,
                "bets": len(bets),
                "profit": sum(bet.profit for bet in bets),
            }
        ),
        flush=True,
    )


@pytest.mark.parametrize("archive_snapshots", [100, 3000])
def test_latest_evaluation_metrics_seek_versions_before_merging_model_names(
    isolated_database, archive_snapshots, monkeypatch
):
    from psycopg2 import sql

    from scripts import feature_importance
    from scripts.model_evaluation_scope import LATEST_METRICS_CTE

    conn, schema = isolated_database
    reference_cte = """WITH latest_metrics AS (
        SELECT DISTINCT ON (source_mem.match_id, source_mv.model_name)
            source_mem.*, source_mv.model_name AS canonical_model_name
        FROM market_efficiency_metrics source_mem
        JOIN model_versions source_mv ON source_mv.id=source_mem.model_version_id
        JOIN official_matches source_match ON source_match.id=source_mem.match_id
        JOIN official_results source_result ON source_result.match_id=source_mem.match_id
        WHERE source_mem.brier_score IS NOT NULL AND source_mem.play_type='spf'
          AND source_mem.snapshot_time<source_match.kickoff_time
          AND source_result.result_status IN ('final','confirmed')
        ORDER BY source_mem.match_id,source_mv.model_name,
                 source_mem.snapshot_time DESC,source_mem.id DESC
    )"""
    suffix = " SELECT id,canonical_model_name FROM latest_metrics ORDER BY id"
    with conn.cursor() as cursor:
        cursor.execute("SET statement_timeout='20s'")
        cursor.execute("""CREATE TABLE market_efficiency_metrics (
            id BIGSERIAL PRIMARY KEY, match_id BIGINT NOT NULL, model_version_id BIGINT,
            play_type TEXT NOT NULL, snapshot_time TIMESTAMP NOT NULL,
            brier_score NUMERIC, log_loss NUMERIC, rps NUMERIC,
            clv_score NUMERIC, probability_gap NUMERIC, favourite_longshot_score NUMERIC)""")
        cursor.execute("""CREATE INDEX idx_mem_model_version
            ON market_efficiency_metrics(model_version_id)""")
        cursor.execute("""INSERT INTO model_versions(model_name)
            VALUES ('maher_poisson'),('maher_poisson'),('elo_rating')""")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-26 18:00'::timestamp FROM generate_series(1,109)""")
        cursor.execute("ALTER TABLE official_matches ADD COLUMN league_name TEXT DEFAULT 'fixture'")
        cursor.execute("UPDATE official_matches SET kickoff_time=NULL WHERE id=106")
        cursor.execute("""INSERT INTO official_results(match_id,result_status,spf_result)
            SELECT id,CASE WHEN id=103 THEN 'provisional' ELSE 'confirmed' END,'3'
            FROM official_matches WHERE id<>104""")
        cursor.execute(
            """INSERT INTO market_efficiency_metrics
                (match_id,model_version_id,play_type,snapshot_time,brier_score,log_loss,rps)
            SELECT m.id,mv.id,'spf','2026-01-01'::timestamp+n*INTERVAL '1 minute',0.6,1,0.2
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n WHERE m.id<=100""",
            (archive_snapshots,),
        )
        cursor.execute("""INSERT INTO market_efficiency_metrics
                (match_id,model_version_id,play_type,snapshot_time,brier_score,log_loss,rps)
            VALUES
                (101,1,'spf','2026-10-25 10:00',0.8,1,0.2),
                (101,2,'spf','2026-10-25 10:00',0.2,1,0.2),
                (101,2,'spf','2026-10-25 12:00',NULL,1,0.2),
                (101,2,'spf','2026-10-26 18:00',0.9,1,0.2),
                (101,2,'spf','2026-10-26 19:00',0.9,1,0.2),
                (101,2,'rqspf','2026-10-25 13:00',0.9,1,0.2),
                (102,1,'spf','2026-10-25 10:00',0.3,1,0.2),
                (102,2,'spf','2026-10-25 09:00',0.9,1,0.2),
                (103,1,'spf','2026-10-25 10:00',0.9,1,0.2),
                (104,1,'spf','2026-10-25 10:00',0.9,1,0.2),
                (105,1,'spf','2026-10-26 19:00',0.9,1,0.2),
                (106,1,'spf','2026-10-25 10:00',0.9,1,0.2),
                (107,1,'spf','2026-10-25 10:00',0.4,1,0.2),
                (107,NULL,'spf','2026-10-25 12:00',0.9,1,0.2),
                (107,9999,'spf','2026-10-25 12:00',0.9,1,0.2),
                (108,1,'spf','2026-10-25 10:00',0.5,1,0.2),
                (108,1,'spf','2026-10-25 10:00',0.6,1,0.2),
                (109,3,'spf','2026-10-25 10:00',0,0,0)""")
        migrations = Path(__file__).resolve().parents[2] / "sql"
        cursor.execute((migrations / "19_backtest_schema.sql").read_text())
        cursor.execute("""INSERT INTO backtest_runs(name,status,created_at)
            VALUES ('old','completed','2026-10-20'),('new','completed','2026-10-21'),
                   ('unfinished','running','2026-10-22')""")
        cursor.execute("""INSERT INTO backtest_run_results
                (run_id,model_name,window_index,roi,hit_rate,total_profit)
            VALUES (1,'maher_poisson',NULL,0.1,0.4,1),
                   (2,'maher_poisson',NULL,0.2,0.5,2),
                   (2,'maher_poisson',1,0.9,0.9,9),
                   (3,'maher_poisson',NULL,0.8,0.8,8)""")
        started = time.perf_counter()
        migration = (migrations / "114_evaluation_read_paths.sql").read_text()
        cursor.execute(migration)
        build_ms = (time.perf_counter() - started) * 1000
        cursor.execute(migration)  # Existing migration prebuild/replay remains safe.
        cursor.execute("""SELECT indisvalid,indisready,pg_relation_size(indexrelid)
            FROM pg_index WHERE indexrelid='idx_mem_identity_latest_scored_spf'::regclass""")
        valid, ready, index_bytes = cursor.fetchone()
        assert valid and ready
        cursor.execute("ANALYZE")
        cursor.execute(reference_cte + suffix)
        expected = cursor.fetchall()
        cursor.execute(LATEST_METRICS_CTE + suffix)
        assert cursor.fetchall() == expected
        cursor.execute(
            reference_cte
            + """ INSERT INTO model_predictions
                (match_id,model_version_id,play_type,option_code,predict_time,
                 model_probability,market_probability,confidence_score,validation_status)
            SELECT match_id,model_version_id,'spf','3',snapshot_time,0.5,0.5,NULL,'valid'
            FROM latest_metrics"""
        )
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute(LATEST_METRICS_CTE + suffix)
        assert cursor.fetchall() == expected
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + LATEST_METRICS_CTE + suffix)
        plan = cursor.fetchone()[0][0]

    comparison = feature_importance.get_model_comparison_data(conn)
    by_name = {model["name"]: model for model in comparison["models"]}
    assert comparison["total_models"] == 2
    assert by_name["maher_poisson"]["n_predictions"] == 104
    assert by_name["maher_poisson"]["brier"] == 0.5913
    assert by_name["maher_poisson"]["roi"] == 0.2
    assert by_name["elo_rating"]["n_predictions"] == 101
    assert by_name["elo_rating"]["brier"] == 0.5941
    assert all(model["closing_edge"] is None for model in comparison["models"])
    summary = feature_importance.get_evaluation_summary(conn)
    assert summary["overall"]["total_evaluated"] == 205
    assert all(model["paired_market_samples"] == 0 for model in summary["models"])
    assert all(model["brier_improvement_vs_market"] is None for model in summary["models"])
    conditions = {}
    for dimension in ("league", "odds_range", "confidence"):
        conditions[dimension] = feature_importance.get_condition_performance(conn, dimension)
        assert sorted(segment["n"] for segment in conditions[dimension]["segments"]) == [101, 104]
    assert all(
        segment["confidence_range"] == "未校准/未知"
        for segment in conditions["confidence"]["segments"]
    )
    with monkeypatch.context() as oracle:
        oracle.setattr(feature_importance, "_LATEST_METRICS_CTE", reference_cte)
        assert feature_importance.get_model_comparison_data(conn) == comparison
        assert feature_importance.get_evaluation_summary(conn) == summary
        for dimension, response in conditions.items():
            assert feature_importance.get_condition_performance(conn, dimension) == response

    def metric_work(node):
        own = 0
        if node.get("Relation Name") == "market_efficiency_metrics":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(metric_work(child) for child in node.get("Plans", []))

    work = metric_work(plan["Plan"])
    assert "idx_mem_identity_latest_scored_spf" in json.dumps(plan)
    print(
        json.dumps(
            {
                "metric_archive_rows": archive_snapshots * 300,
                "metric_node_rows_examined": work,
                "execution_time_ms": plan["Execution Time"],
                "index_build_ms": build_ms,
                "index_bytes": index_bytes,
            }
        ),
        flush=True,
    )
    assert work < 20000, "latest model metrics must not sort repeated historical snapshots"


def test_model_overview_aggregates_global_latest_predictions_once(isolated_database, monkeypatch):
    from apps.backend.src.routers import predictions as router

    conn, _ = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("""ALTER TABLE model_versions
            ADD COLUMN version TEXT DEFAULT 'fixture',
            ADD COLUMN is_active BOOLEAN DEFAULT true,
            ADD COLUMN training_start_date DATE,
            ADD COLUMN training_end_date DATE,
            ADD COLUMN created_at TIMESTAMP DEFAULT now()""")
        cursor.execute("""CREATE TABLE probability_calibration_profiles (
            id BIGSERIAL PRIMARY KEY, model_name TEXT, play_type TEXT, method_name TEXT,
            sample_count INTEGER, log_loss_before NUMERIC, log_loss_after NUMERIC,
            parameters_json JSONB, training_end_date DATE, is_active BOOLEAN,
            created_at TIMESTAMP DEFAULT now())""")
        cursor.execute("""INSERT INTO model_versions (model_name)
            VALUES ('market_baseline'), ('elo_rating'), ('maher_poisson')""")
        cursor.execute("""INSERT INTO official_matches (kickoff_time)
            SELECT '2026-10-25 18:00'::timestamp FROM generate_series(1,1000)""")
        cursor.execute("""INSERT INTO model_predictions (
            match_id, model_version_id, predict_time, play_type,
            option_code, model_probability, validation_status)
            SELECT m.id, mv.id, '2026-10-24 00:00'::timestamp + n * INTERVAL '1 minute',
                   'spf', option_code, 0.333333,
                   CASE WHEN mv.model_name = 'elo_rating' AND n=100 THEN 'invalid' ELSE 'valid' END
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,100) n CROSS JOIN unnest(ARRAY['3','1','0']) option_code""")
        cursor.execute("ANALYZE model_predictions")
        cursor.execute("ANALYZE model_versions")
        cursor.execute("ANALYZE official_matches")
        migration = (
            Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql"
        ).read_text()
        cursor.execute(migration)
    conn.commit()

    capture = MagicMock()
    capture.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setattr(router, "get_db", lambda: nullcontext(capture))
    router.get_prediction_model_overview()
    query, params = capture.cursor.return_value.__enter__.return_value.execute.call_args.args
    assert "WITH RECURSIVE" in query
    assert "FROM model_prediction_latest_rows" not in query
    assert "FROM legacy_latest" in query

    with conn.cursor() as cursor:
        cursor.execute(query, params)
        rows = cursor.fetchall()
        actual = {row[1]: (row[7], row[8]) for row in rows}
        cursor.execute("""SELECT model_version_id, COUNT(DISTINCT match_id), MAX(predict_time)
            FROM model_prediction_latest_rows WHERE validation_status='valid'
            GROUP BY model_version_id""")
        expected = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}
        assert actual == {model_id: expected.get(model_id, (0, None)) for model_id in actual}
        # The newest invalid elo rows must hide its older valid forecasts,
        # matching the existing latest-view semantics.
        assert [row[7] for row in rows if row[0] == "elo_rating"] == [0]
        cursor.execute("EXPLAIN (ANALYZE, FORMAT JSON) " + query, params)
        plan = cursor.fetchone()[0][0]

    def windows(node):
        if node["Node Type"] == "WindowAgg":
            yield node["Actual Loops"]
        for child in node.get("Plans", []):
            yield from windows(child)

    def indexes(node):
        if node.get("Index Name"):
            yield node["Index Name"]
        for child in node.get("Plans", []):
            yield from indexes(child)

    loops = list(windows(plan["Plan"]))
    used_indexes = set(indexes(plan["Plan"]))
    print(
        json.dumps(
            {
                "fixture_rows": 900000,
                "execution_time_ms": plan["Execution Time"],
                "global_ranking_loops": loops,
                "used_indexes": sorted(used_indexes),
            }
        )
    )
    assert not loops, "model overview should seek latest identities instead of ranking history"
    assert "idx_predictions_identity_latest" in used_indexes


@pytest.mark.parametrize("archive_snapshots", [100, 1000])
def test_pool_consensus_preserves_latest_evidence_without_ranking_history(
    isolated_database, archive_snapshots
):
    from psycopg2 import sql

    from apps.backend.src.routers.pool import _read_pool_model_consensus
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, schema = isolated_database
    target_ids = list(range(101, 115))
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL jit = off")
        cursor.execute("ALTER TABLE model_versions ADD COLUMN is_active BOOLEAN DEFAULT true")
        cursor.execute("""INSERT INTO model_versions(model_name,is_active)
            VALUES ('shared',true),('shared',true),('independent',true),('shared',false)""")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-25 20:00'::timestamp FROM generate_series(1,114)""")
        cursor.execute(
            """INSERT INTO model_predictions
                (match_id,model_version_id,predict_time,play_type,option_code,
                 model_probability,validation_status,uncertainty_reason)
            SELECT m.id,mv.id,'2026-01-01'::timestamp+n*INTERVAL '1 minute',
                   'spf',o,0.333333,'valid','{"model_independent":true}'::jsonb
            FROM official_matches m CROSS JOIN model_versions mv
            CROSS JOIN generate_series(1,%s) n CROSS JOIN unnest(ARRAY['3','1','0']) o
            WHERE (m.id<=100 AND mv.id<=3) OR (m.id>100 AND mv.id=1)""",
            (archive_snapshots,),
        )
        rows = []

        def vector(
            match,
            version=1,
            when="2026-10-25 10:00",
            values=(0.2, 0.3, 0.5),
            status="valid",
            independent=True,
        ):
            for option, probability in zip(("3", "1", "0"), values, strict=True):
                rows.append(
                    (
                        match,
                        version,
                        when,
                        option,
                        probability,
                        status,
                        json.dumps({"model_independent": independent}),
                    )
                )

        for match_id in target_ids:
            vector(match_id)
        vector(101, 2, "2026-10-25 11:00", (0.4, 0.35, 0.25))
        vector(102, 4, "2026-10-25 11:00")
        vector(103, when="2026-10-25 11:00", status="invalid")
        vector(104, 2, "2026-10-25 11:00")
        vector(105, when="2026-10-25 11:00", independent=False)
        vector(106, when="2026-10-25 11:00", independent=None)
        vector(107, 3, "2026-10-25 11:00", (0.6, 0.2, 0.2))
        vector(108, when="2026-10-25 11:00", values=(0.2, None, 0.5))
        vector(111, when="2026-10-25 10:00", values=(0.5, 0.3, 0.2))
        vector(114, when="2026-10-25 11:00", status=None)
        cursor.executemany(
            """INSERT INTO model_predictions
            (match_id,model_version_id,predict_time,play_type,option_code,
             model_probability,validation_status,uncertainty_reason)
            VALUES (%s,%s,%s,'spf',%s,%s,%s,%s::jsonb)""",
            rows,
        )
        cursor.execute("UPDATE official_matches SET kickoff_time='2026-10-25 10:30' WHERE id=104")
        cursor.execute("UPDATE official_matches SET kickoff_time=NULL WHERE id=113")
        cursor.execute(
            (Path(__file__).resolve().parents[2] / "sql/113_prediction_read_paths.sql").read_text()
        )
    conn.commit()

    # A published complete vector takes priority over newer legacy rows. Rows
    # mapped to an unfinished run cannot replace the last published/legacy evidence.
    for match_id, completed in ((109, True), (110, False)):
        run_id = uuid.uuid4()
        create_prediction_run(
            conn,
            run_id=run_id,
            ai_job_run_id=None,
            release_id="pool-fixture",
            code_fingerprint={"files": {}, "sha256": content_sha256({})},
            model_manifest=[{"model_version_id": 2}],
            input_manifest={"match_ids": [match_id]},
            provenance_status="incomplete",
        )
        metadata = {
            "match_id": match_id,
            "model_version_id": 2,
            "play_type": "spf",
            "predict_time": "2026-10-25T09:00:00" if completed else "2026-10-25T11:00:00",
            "feature_snapshot_id": 77,
            "expected_options": ["3", "1", "0"],
        }
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata=metadata,
            predictions=[
                {
                    **{k: v for k, v in metadata.items() if k != "expected_options"},
                    "option_code": option,
                    "model_probability": probability,
                    "validation_status": "valid",
                    "calculation_version": "pool-fixture",
                    "uncertainty_reason": {"model_independent": True},
                    "odds_snapshot_id": 30,
                    "market_probability": probability,
                    "break_even_probability": probability,
                    "market_edge": 0,
                    "breakeven_edge": 0,
                    "ev": 0,
                }
                for option, probability in (("3", 0.6), ("1", 0.25), ("0", 0.15))
            ],
        )
        if completed:
            finalize_prediction_run(
                conn,
                run_id=run_id,
                run_status="completed",
                output_summary={
                    "expected_groups": 1,
                    "completed_groups": 1,
                    "skipped_groups": 0,
                    "missing_groups": [],
                    "input_updates_skipped": 0,
                    "completion_reason": "predictions_completed",
                },
            )
    with conn.cursor() as cursor:
        cursor.execute("ANALYZE")
        cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cursor.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute("SET LOCAL jit = off")
        # Independent oracle: the original canonical view and pool filters.
        cursor.execute(
            """SELECT mp.match_id,
            AVG(mp.model_probability) FILTER (WHERE mp.option_code='3'),
            AVG(mp.model_probability) FILTER (WHERE mp.option_code='1'),
            AVG(mp.model_probability) FILTER (WHERE mp.option_code='0')
            FROM model_prediction_latest_rows mp
            JOIN model_versions mv ON mv.id=mp.model_version_id
            JOIN official_matches m ON m.id=mp.match_id
            WHERE mp.match_id=ANY(%s) AND mp.play_type='spf'
              AND mp.predict_time<m.kickoff_time AND mp.validation_status='valid'
              AND COALESCE((mp.uncertainty_reason->>'model_independent')::boolean,false)=true
              AND mv.is_active=true AND mp.model_probability IS NOT NULL
            GROUP BY mp.match_id""",
            (target_ids,),
        )
        expected = {int(row[0]): tuple(row[1:]) for row in cursor.fetchall()}

        class CaptureCursor:
            def execute(self, query, params):
                self.query, self.params = query, params
                cursor.execute(query, params)

            def fetchall(self):
                return cursor.fetchall()

        capture = CaptureCursor()
        assert _read_pool_model_consensus(capture, target_ids) == expected
        assert tuple(map(float, expected[101])) == (0.4, 0.35, 0.25)
        assert all(match not in expected for match in (102, 103, 104, 105, 106, 113, 114))
        assert tuple(map(float, expected[107])) == (0.4, 0.25, 0.35)
        assert expected[108][1] is None
        assert tuple(map(float, expected[109])) == (0.6, 0.25, 0.15)
        assert tuple(map(float, expected[110])) == (0.2, 0.3, 0.5)
        assert tuple(map(float, expected[111])) == (0.5, 0.3, 0.2)
        cursor.execute("EXPLAIN (ANALYZE,FORMAT JSON) " + capture.query, capture.params)
        plan = cursor.fetchone()[0][0]

    def prediction_work(node):
        own = 0
        if node.get("Relation Name") == "model_predictions":
            own = (node["Actual Rows"] + node.get("Rows Removed by Filter", 0)) * node[
                "Actual Loops"
            ]
        return own + sum(prediction_work(child) for child in node.get("Plans", []))

    work = prediction_work(plan["Plan"])
    print(
        json.dumps(
            {
                "pool_archive_rows": 942 * archive_snapshots,
                "prediction_node_rows_examined": work,
                "execution_time_ms": plan["Execution Time"],
            }
        ),
        flush=True,
    )
    assert work < 5000, "pool consensus must seek latest identities, not rank selected history"


def test_pool_issue_and_prediction_reads_share_one_database_snapshot(
    isolated_database, monkeypatch
):
    import psycopg2
    from psycopg2 import sql

    from apps.backend.src.routers import pool

    conn, schema = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("ALTER TABLE model_versions ADD COLUMN is_active BOOLEAN DEFAULT true")
        cursor.execute("ALTER TABLE official_matches ADD COLUMN league_name TEXT")
        cursor.execute("INSERT INTO model_versions(model_name) VALUES ('pool-snapshot')")
        cursor.execute("""INSERT INTO official_matches(kickoff_time)
            SELECT '2026-10-25 20:00'::timestamp FROM generate_series(1,14)""")
        cursor.execute("""CREATE TABLE football_pool_issues (
            id INT, issue_no TEXT, game_type TEXT, total_matches INT, official_status TEXT,
            sale_stop_time TIMESTAMP, updated_at TIMESTAMP)""")
        cursor.execute("""INSERT INTO football_pool_issues
            VALUES (1,'26103','t14c',14,'selling','2026-10-25 18:00',now())""")
        cursor.execute("""CREATE TABLE football_pool_issue_matches (
            issue_id INT, match_order INT, match_id BIGINT, home_team_name TEXT,
            away_team_name TEXT, league_name TEXT, kickoff_time TIMESTAMP)""")
        cursor.execute("""INSERT INTO football_pool_issue_matches
            SELECT 1,id,id,'home-'||id,'away-'||id,'fixture',kickoff_time FROM official_matches""")
        cursor.execute("""INSERT INTO model_predictions
            (match_id,model_version_id,predict_time,play_type,option_code,
             model_probability,validation_status,uncertainty_reason)
            SELECT id,1,'2026-10-25 10:00','spf',o,0.333333,'valid',
                   '{"model_independent":true}'::jsonb
            FROM official_matches CROSS JOIN unnest(ARRAY['3','1','0']) o""")
    conn.commit()
    statements = []

    class RuntimeCursor:
        def __enter__(self):
            self.raw = conn.cursor()
            return self

        def __exit__(self, *args):
            self.raw.close()

        def execute(self, query, params=None):
            self.query = query
            statements.append(query)
            self.raw.execute(query, params)

        def fetchall(self):
            rows = self.raw.fetchall()
            if "FROM football_pool_issues i" in self.query:
                # A collector commits a correction between the two read queries.
                with closing(psycopg2.connect(conn.dsn)) as writer:
                    with writer.cursor() as other:
                        other.execute(
                            sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                        )
                        other.execute("UPDATE official_matches SET kickoff_time='2026-10-25 09:00'")
                    writer.commit()
            return rows

    runtime = MagicMock()
    runtime.rollback.side_effect = conn.rollback
    runtime.cursor.side_effect = RuntimeCursor
    observed = []
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(runtime))
    monkeypatch.setattr(
        pool, "analyze_pool", lambda matches, **kwargs: observed.extend(matches) or {}
    )
    monkeypatch.setattr(pool, "pool_analysis_to_dict", lambda value: value)
    try:
        result = pool.run_pool_analysis(
            budget=256, strategy="balanced", seed_match_id=None, issue_id=None
        )
        assert result["issue"]["issue_no"] == "26103"
        assert len(observed) == 14
        assert all(match.prob_home == 0.333333 for match in observed)
        assert all(match.match_date == "2026-10-25 20:00:00" for match in observed)
        assert len([query for query in statements if "latest_model_options" in query]) == 1
    finally:
        conn.rollback()
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM official_matches WHERE kickoff_time='2026-10-25 09:00'"
        )
        assert cursor.fetchone()[0] == 14


@pytest.fixture
def isolated_database(request):
    dsn = os.environ.get("FQP_P106_TEST_DATABASE_URL", "").strip()
    if not dsn:
        pytest.skip("set FQP_P106_TEST_DATABASE_URL to an isolated local fqp_p106_test_* database")

    parsed = urlparse(dsn)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("P106 PostgreSQL tests only accept a loopback database host")
    if not parsed.path.lstrip("/").startswith("fqp_p106_test_"):
        pytest.fail("P106 PostgreSQL tests require a database named fqp_p106_test_*")

    psycopg2 = pytest.importorskip("psycopg2")
    from psycopg2 import sql

    connection = psycopg2.connect(dsn)
    connection.autocommit = True
    schema_name = f"p106_{uuid.uuid4().hex}"
    role_created = False
    schema_created = False

    def cleanup() -> None:
        try:
            if not connection.closed:
                if not connection.autocommit:
                    connection.rollback()
                connection.autocommit = True
                with connection.cursor() as cursor:
                    cursor.execute("SET search_path TO public")
                    if schema_created:
                        cursor.execute(
                            sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name))
                        )
                if role_created:
                    with connection.cursor() as cursor:
                        cursor.execute("DROP ROLE fqp")
        finally:
            connection.close()

    request.addfinalizer(cleanup)
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_roles WHERE rolname='fqp'")
        if cursor.fetchone() is None:
            cursor.execute("CREATE ROLE fqp NOLOGIN")
            role_created = True
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        schema_created = True
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        cursor.execute("CREATE TABLE ai_job_runs (id BIGSERIAL PRIMARY KEY)")
        cursor.execute(
            "CREATE TABLE model_versions (id BIGSERIAL PRIMARY KEY, model_name VARCHAR(128) NOT NULL)"
        )
        cursor.execute(
            """CREATE TABLE official_matches (
                id BIGSERIAL PRIMARY KEY,
                business_date DATE,
                kickoff_time TIMESTAMP,
                match_status VARCHAR(32),
                home_team_name TEXT,
                away_team_name TEXT
            )"""
        )
        cursor.execute(
            """CREATE TABLE teams (
                id BIGSERIAL PRIMARY KEY,
                team_name_cn TEXT NOT NULL
            )"""
        )
        cursor.execute(
            """CREATE TABLE official_results (
                id BIGSERIAL PRIMARY KEY,
                match_id BIGINT NOT NULL,
                official_publish_time TIMESTAMP,
                full_home_goals INTEGER,
                full_away_goals INTEGER,
                result_status VARCHAR(32),
                spf_result VARCHAR(8)
            )"""
        )
        cursor.execute(
            """CREATE TABLE official_odds_snapshots (
                id BIGSERIAL PRIMARY KEY,
                match_id BIGINT NOT NULL,
                play_type VARCHAR(32) NOT NULL,
                option_code VARCHAR(16) NOT NULL,
                sp_value NUMERIC(10,4) NOT NULL,
                snapshot_time TIMESTAMP NOT NULL,
                is_open BOOLEAN NOT NULL DEFAULT true
            )"""
        )
        cursor.execute(
            """CREATE TABLE backtest_runs (
                id BIGSERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                config JSONB NOT NULL DEFAULT '{}',
                status VARCHAR(32) NOT NULL,
                started_at TIMESTAMPTZ,
                finished_at TIMESTAMPTZ,
                error_message TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )"""
        )
        cursor.execute(
            """CREATE TABLE model_predictions (
                id BIGSERIAL PRIMARY KEY,
                match_id BIGINT NOT NULL,
                model_version_id BIGINT NOT NULL,
                odds_snapshot_id BIGINT,
                feature_snapshot_id BIGINT,
                predict_time TIMESTAMP NOT NULL,
                play_type VARCHAR(32) NOT NULL,
                option_code VARCHAR(64) NOT NULL,
                raw_model_probability NUMERIC(10,6),
                model_probability NUMERIC(10,6),
                market_probability NUMERIC(10,6),
                probability_lower_bound NUMERIC(10,6),
                probability_upper_bound NUMERIC(10,6),
                uncertainty_score NUMERIC(10,6),
                adjusted_probability NUMERIC(10,6),
                fair_odds NUMERIC(10,4), ev NUMERIC(10,6),
                confidence_score NUMERIC(10,4), risk_score NUMERIC(10,4),
                break_even_probability NUMERIC(10,6), market_edge NUMERIC(10,6),
                breakeven_edge NUMERIC(10,6), validation_status VARCHAR(32),
                validation_errors JSONB, calculation_version VARCHAR(64),
                uncertainty_reason JSONB, created_at TIMESTAMP DEFAULT now()
            )"""
        )

    with connection.cursor() as cursor:
        migrations_dir = Path(__file__).resolve().parents[2] / "sql"
        cursor.execute(
            (migrations_dir / "111_prediction_run_identity.sql").read_text(encoding="utf-8")
        )
        cursor.execute(
            (migrations_dir / "112_model_training_manifest.sql").read_text(encoding="utf-8")
        )

    connection.autocommit = False
    yield connection, schema_name


def test_maher_training_query_excludes_ambiguous_team_names_with_candidate_audit(
    isolated_database,
):
    from scripts.mle_trainer import _load_training_dataset

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.executemany(
            "INSERT INTO teams (team_name_cn) VALUES (%s)",
            [("Shared FC",), ("Shared FC",), ("Away One",), ("Home One",)],
        )
        cursor.execute(
            """INSERT INTO official_matches (
                   business_date, kickoff_time, match_status,
                   home_team_name, away_team_name
               ) VALUES
                   ('2026-01-01', '2026-01-01 18:00:00', 'settled', 'Shared FC', 'Away One'),
                   ('2026-01-02', '2026-01-02 18:00:00', 'settled', 'Home One', 'Away One'),
                   ('2026-01-03', '2026-01-03 18:00:00', 'scheduled', 'Shared FC', 'Away One')
               RETURNING id"""
        )
        match_ids = [row[0] for row in cursor.fetchall()]
        cursor.executemany(
            """INSERT INTO official_results (
                   match_id, official_publish_time, full_home_goals, full_away_goals
               ) VALUES (%s, %s, %s, %s)""",
            [
                (match_ids[0], "2026-01-02 00:00:00", 1, 0),
                (match_ids[1], "2026-01-03 00:00:00", 2, 1),
            ],
        )

    dataset = _load_training_dataset(conn, min_matches=1)

    assert [sample.match_id for sample in dataset.samples] == [match_ids[1]]
    assert [(entry.match_id, entry.reason) for entry in dataset.manifest.excluded] == [
        (match_ids[0], "team_identity_ambiguous:home=[1,2]"),
        (
            match_ids[2],
            "match_not_settled;team_identity_ambiguous:home=[1,2]",
        ),
    ]


def test_prediction_groups_publish_atomically_and_are_read_group_first(
    isolated_database, monkeypatch
):
    from scripts.model_prediction_run_identity import canonical_json_bytes, content_sha256
    from scripts.model_prediction_run_loader import load_latest_prediction_group
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
        update_prediction_run_manifest,
    )

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher_poisson') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]

    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-release",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[{"model_version_id": model_version_id}],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )
    with pytest.raises(RaiseException, match="prediction run identity is immutable"):
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE model_prediction_runs SET release_id='tampered' WHERE id=%s",
                (str(run_id),),
            )
    conn.rollback()
    metadata = {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["3", "1", "0"],
        "odds_snapshot_ids": {"3": 30, "1": 31, "0": 32},
        "feature_snapshot_id": 77,
        "input_fence": {"match_id": match_id, "input_version": 1},
    }
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "odds_snapshot_id": 30 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "raw_model_probability": probability,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "validation_errors": [],
            "calculation_version": "test-v1",
        }
        for index, (option, probability) in enumerate((("3", 0.5), ("1", 0.25), ("0", 0.25)))
    ]

    group_id = store_prediction_group(
        conn,
        run_id=run_id,
        metadata=metadata,
        predictions=predictions,
    )
    with pytest.raises(
        RaiseException, match="prediction run manifest is immutable after output begins"
    ):
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE model_prediction_runs SET input_manifest='{}'::jsonb WHERE id=%s",
                (str(run_id),),
            )
    conn.rollback()
    finalize_prediction_run(
        conn,
        run_id=run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )
    with pytest.raises(RaiseException, match="terminal prediction runs are immutable"):
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE model_prediction_runs SET input_manifest='{}'::jsonb WHERE id=%s",
                (str(run_id),),
            )
    conn.rollback()

    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        next_job_id = cursor.fetchone()[0]
    next_run_id = uuid.uuid4()
    artifact_identity = {
        "model_version_id": model_version_id,
        "model_name": "maher_poisson",
        "provenance_status": "complete",
        "parameters_sha256": "a" * 64,
        "artifact": {"kind": "inline_parameters", "sha256": "a" * 64, "size_bytes": 0},
        "training_manifest_sha256": "b" * 64,
        "training_identity_sha256": "c" * 64,
    }
    create_prediction_run(
        conn,
        run_id=next_run_id,
        ai_job_run_id=next_job_id,
        release_id="test-release-2",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[{"model_version_id": model_version_id}],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )
    update_prediction_run_manifest(
        conn,
        run_id=next_run_id,
        model_manifest=[artifact_identity],
        input_manifest={"match_ids": [match_id], "predict_time": "2026-10-23T10:00:00"},
        provenance_status="complete",
    )
    # Two runs at the exact same prediction timestamp must still publish one
    # complete vector based on the run/group tie-breaker.
    next_metadata = {
        **metadata,
        "artifact_identity": artifact_identity,
        "provenance_status": "complete",
    }
    next_predictions = copy.deepcopy(predictions)
    for row, probability in zip(next_predictions, (0.2, 0.3, 0.5), strict=True):
        row["model_probability"] = probability
        row["raw_model_probability"] = probability
        row["market_probability"] = probability
    from scripts import model_prediction_run_storage as storage

    with monkeypatch.context() as patcher:
        patcher.setattr(
            storage,
            "canonical_json_bytes",
            lambda value: json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"),
        )
        next_group_id = store_prediction_group(
            conn,
            run_id=next_run_id,
            metadata=next_metadata,
            predictions=next_predictions,
        )
    finalize_prediction_run(
        conn,
        run_id=next_run_id,
        run_status="partial",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 1,
            "completion_reason": "input_update_unavailable",
        },
    )

    loaded = load_latest_prediction_group(
        conn, match_id=match_id, model_version_id=model_version_id, play_type="spf"
    )
    assert str(loaded["group_id"]) == str(next_group_id)
    assert str(loaded["group_id"]) != str(group_id)
    assert loaded["status"] == "complete", loaded.get("integrity_error")
    assert sorted(row["option_code"] for row in loaded["options"]) == ["0", "1", "3"]
    assert loaded["probability_vector"] == {"0": 0.5, "1": 0.3, "3": 0.2}
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT output_manifest, output_manifest_canonical "
            "FROM model_prediction_groups WHERE id=%s",
            (str(next_group_id),),
        )
        persisted_manifest, persisted_bytes = cursor.fetchone()
    persisted_bytes = bytes(persisted_bytes)
    assert json.loads(persisted_bytes.decode("utf-8")) == persisted_manifest
    assert persisted_bytes != canonical_json_bytes(persisted_manifest)

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT output_sha256 FROM model_prediction_groups WHERE id=%s",
            (str(next_group_id),),
        )
        output_sha256 = cursor.fetchone()[0]
        assert hashlib.sha256(persisted_bytes).hexdigest() == output_sha256
        with pytest.raises(RaiseException, match="run-aware prediction rows are immutable"):
            cursor.execute(
                "UPDATE model_predictions SET model_probability=0.7 WHERE id=%s",
                (loaded["options"][0]["prediction_id"],),
            )
    conn.rollback()

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM model_prediction_group_options WHERE group_id=%s",
            (str(group_id),),
        )
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            "SELECT COUNT(*) FROM model_prediction_latest_rows WHERE match_id=%s", (match_id,)
        )
        assert cursor.fetchone()[0] == 3
        cursor.execute(
            """SELECT run_status, provenance_status, run_manifest, run_manifest_sha256
               FROM model_prediction_runs WHERE id=%s""",
            (str(next_run_id),),
        )
        status_row = cursor.fetchone()
        assert status_row[0] == "partial"
        assert status_row[1] == "complete"
        assert status_row[3] == content_sha256(
            {key: value for key, value in status_row[2].items() if key != "sha256"}
        )
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        duplicate_job_id = cursor.fetchone()[0]
    duplicate_run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=duplicate_run_id,
        ai_job_run_id=duplicate_job_id,
        release_id="test-duplicate-output-keys",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[artifact_identity],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
    )
    from scripts import model_prediction_run_storage as storage

    def serialize_with_duplicate_match_key(value):
        raw = canonical_json_bytes(value)
        if isinstance(value, dict) and "prediction_outputs" in value:
            return raw[:-1] + f',"match_id":{value["match_id"]}}}'.encode()
        return raw

    with monkeypatch.context() as patcher:
        patcher.setattr(storage, "canonical_json_bytes", serialize_with_duplicate_match_key)
        with pytest.raises(RaiseException, match="duplicate JSON object keys"):
            store_prediction_group(
                conn,
                run_id=duplicate_run_id,
                metadata=next_metadata,
                predictions=next_predictions,
            )
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM model_prediction_groups WHERE run_id=%s",
            (str(duplicate_run_id),),
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        legacy_match_id = cursor.fetchone()[0]
        for option, probability in (("3", 0.4), ("1", 0.35), ("0", 0.25)):
            cursor.execute(
                """INSERT INTO model_predictions (
                       match_id, model_version_id, predict_time, play_type,
                       option_code, model_probability, market_probability,
                       validation_status, calculation_version
                   ) VALUES (%s, %s, '2026-10-23T10:00:00', 'spf', %s, %s, %s, 'valid', 'market_metrics_v2')""",
                (legacy_match_id, model_version_id, option, probability, probability),
            )

    legacy = load_latest_prediction_group(
        conn, match_id=legacy_match_id, model_version_id=model_version_id, play_type="spf"
    )
    assert legacy["status"] == "legacy-unbound"
    assert legacy["run_id"] is None
    assert sorted(legacy["probability_vector"]) == ["0", "1", "3"]


def test_prediction_group_cannot_be_inserted_as_complete(isolated_database):
    conn, _schema_name = isolated_database
    from scripts.model_prediction_run_storage import create_prediction_run

    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher_poisson') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-release",
        code_fingerprint={"sha256": "d" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="complete",
    )

    with pytest.raises(RaiseException, match="prediction groups must start in building state"):
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_prediction_groups (
                       id, run_id, match_id, model_version_id, play_type, market_variant,
                       predict_time, expected_options, probability_vector, odds_snapshot_ids,
                       odds_snapshot_times, output_manifest, provenance_status, output_sha256,
                       group_status, completed_at
                   ) VALUES (
                       %s, %s, %s, %s, 'spf', '', '2026-10-23T10:00:00',
                       '["3","1","0"]'::jsonb, '{"3":0.5,"1":0.25,"0":0.25}'::jsonb,
                       '{"3":30,"1":31,"0":32}'::jsonb, '{}'::jsonb, '{}'::jsonb,
                       'incomplete', %s, 'complete', clock_timestamp()
                   )""",
                (str(uuid.uuid4()), str(run_id), match_id, model_version_id, "e" * 64),
            )
    conn.rollback()


def test_prediction_run_cannot_be_completed_with_reported_missing_groups(isolated_database):
    from psycopg2 import Binary
    from psycopg2.extras import Json

    from scripts.model_prediction_run_identity import canonical_json_bytes, content_sha256

    conn, _schema_name = isolated_database
    from scripts.model_prediction_run_storage import create_prediction_run

    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-completion-integrity",
        code_fingerprint={"sha256": "c" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="incomplete",
    )

    summary = {
        "expected_groups": 1,
        "completed_groups": 0,
        "skipped_groups": 1,
        "missing_groups": [{"reason": "odds_missing"}],
        "input_updates_skipped": 0,
        "completion_reason": "missing_output",
    }
    output_manifest = {"groups": [], "summary": summary}
    with pytest.raises(
        RaiseException, match="completed prediction run cannot have skipped outputs"
    ):
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE model_prediction_runs
                   SET run_status='completed', finished_at=clock_timestamp(),
                       output_manifest_sha256=%s,
                       output_summary=%s, output_manifest=%s,
                       output_manifest_canonical=%s
                   WHERE id=%s""",
                (
                    content_sha256(output_manifest),
                    Json(summary),
                    Json(output_manifest),
                    Binary(canonical_json_bytes(output_manifest)),
                    str(run_id),
                ),
            )
    conn.rollback()


def test_prediction_run_output_manifest_digest_is_checked_by_database(isolated_database):
    from psycopg2 import Binary
    from psycopg2.extras import Json

    from scripts.model_prediction_run_identity import canonical_json_bytes
    from scripts.model_prediction_run_storage import create_prediction_run

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-run-output-hash",
        code_fingerprint={"sha256": "e" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="incomplete",
    )
    summary = {
        "expected_groups": 0,
        "completed_groups": 0,
        "skipped_groups": 0,
        "missing_groups": [],
        "input_updates_skipped": 0,
        "completion_reason": "no_predictable_inputs",
    }
    output_manifest = {"groups": [], "summary": summary}
    with pytest.raises(RaiseException, match="prediction run output manifest SHA-256"):
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE model_prediction_runs
                   SET run_status='completed', finished_at=clock_timestamp(),
                       output_summary=%s, output_manifest=%s,
                       output_manifest_canonical=%s, output_manifest_sha256=%s
                   WHERE id=%s""",
                (
                    Json(summary),
                    Json(output_manifest),
                    Binary(canonical_json_bytes(output_manifest)),
                    "d" * 64,
                    str(run_id),
                ),
            )
    conn.rollback()


def test_failed_run_without_output_summary_preserves_unknown_counts(isolated_database):
    from scripts.model_prediction_run_storage import create_prediction_run, fail_prediction_run

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-failed-summary-unknown",
        code_fingerprint={"sha256": "f" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="incomplete",
    )

    fail_prediction_run(conn, run_id, "failed before output summary was produced")

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT run_status, output_summary, output_manifest "
            "FROM model_prediction_runs WHERE id=%s",
            (str(run_id),),
        )
        run_status, summary, output_manifest = cursor.fetchone()
    assert run_status == "failed"
    assert summary["expected_groups"] is None
    assert summary["completed_groups"] == 0
    assert summary["skipped_groups"] is None
    assert summary["input_updates_skipped"] is None
    assert summary["counts_complete"] is False
    assert output_manifest["summary"] == summary


@pytest.mark.parametrize(
    "fractional_field",
    ("completed_groups", "expected_groups", "skipped_groups", "input_updates_skipped"),
)
def test_prediction_run_summary_rejects_fractional_counts(isolated_database, fractional_field):
    from psycopg2 import Binary
    from psycopg2.extras import Json

    from scripts.model_prediction_run_identity import canonical_json_bytes
    from scripts.model_prediction_run_storage import create_prediction_run

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id=f"test-fractional-summary-{fractional_field}",
        code_fingerprint={"sha256": "c" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="incomplete",
    )
    summary = {
        "expected_groups": 0,
        "completed_groups": 0,
        "skipped_groups": 0,
        "missing_groups": [],
        "input_updates_skipped": 0,
        "completion_reason": "failed_before_output_summary",
    }
    summary[fractional_field] = 0.4
    output_manifest = {"groups": [], "summary": summary}
    output_bytes = canonical_json_bytes(output_manifest)
    with pytest.raises(RaiseException, match="summary counts must be integers"):
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE model_prediction_runs
                   SET run_status='failed', finished_at=clock_timestamp(),
                       output_summary=%s, output_manifest=%s,
                       output_manifest_canonical=%s, output_manifest_sha256=%s,
                       error_message='fractional summary probe'
                   WHERE id=%s""",
                (
                    Json(summary),
                    Json(output_manifest),
                    Binary(output_bytes),
                    hashlib.sha256(output_bytes).hexdigest(),
                    str(run_id),
                ),
            )
    conn.rollback()


def test_manifest_validation_helper_is_executable_by_application_role(isolated_database):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json

    from scripts.model_prediction_run_storage import create_prediction_run

    conn, schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
        cursor.execute(
            sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema_name))
        )
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-manifest-helper-application-role",
        code_fingerprint={"sha256": "a" * 64},
        model_manifest=[],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )

    raw_manifest = f'{{"match_id":{match_id},"match_id":{match_id}}}'.encode()
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE fqp")
        cursor.execute(
            """INSERT INTO model_prediction_groups (
                   id, run_id, match_id, model_version_id, play_type, market_variant,
                   predict_time, expected_options, probability_vector, odds_snapshot_ids,
                   odds_snapshot_times, output_manifest, output_manifest_canonical,
                   provenance_status, output_sha256, group_status, created_at
               ) VALUES (
                   %s, %s, %s, %s, 'spf', '', '2026-10-23T10:00:00',
                   %s, %s, %s, %s, %s, %s, 'incomplete', %s, 'building', clock_timestamp()
               )""",
            (
                str(uuid.uuid4()),
                str(run_id),
                match_id,
                model_version_id,
                Json(["0", "1", "3"]),
                Json({}),
                Json({}),
                Json({}),
                Json({"match_id": match_id}),
                psycopg2.Binary(raw_manifest),
                hashlib.sha256(raw_manifest).hexdigest(),
            ),
        )
        with pytest.raises(RaiseException, match="duplicate JSON object keys"):
            cursor.execute(
                """UPDATE model_prediction_groups
                   SET group_status='complete', completed_at=clock_timestamp()
                   WHERE run_id=%s""",
                (str(run_id),),
            )
    conn.rollback()


def test_option_insert_waits_for_group_publication_and_is_rejected(isolated_database):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json

    from scripts.model_prediction_run_storage import (
        build_prediction_group_payload,
        create_prediction_run,
    )
    from scripts.model_storage import store_model_prediction

    conn, schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-option-publication-lock",
        code_fingerprint={"sha256": "b" * 64},
        model_manifest=[],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )

    metadata = {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["3", "1", "0"],
        "odds_snapshot_ids": {"3": 30, "1": 31, "0": 32},
        "feature_snapshot_id": 77,
    }
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "odds_snapshot_id": 30 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "raw_model_probability": probability,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "validation_errors": [],
            "calculation_version": "test-v1",
        }
        for index, (option, probability) in enumerate((("3", 0.5), ("1", 0.25), ("0", 0.25)))
    ]
    payload = build_prediction_group_payload(
        run_id=run_id,
        metadata=metadata,
        predictions=predictions,
    )
    group_id = uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO model_prediction_groups (
                   id, run_id, match_id, model_version_id, play_type, market_variant,
                   predict_time, expected_options, probability_vector, score_matrix,
                   odds_snapshot_ids, odds_snapshot_times, feature_snapshot_id,
                   input_fence, artifact_identity, output_manifest,
                   output_manifest_canonical, provenance_status, output_sha256,
                   group_status, created_at
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, %s, 'building', clock_timestamp()
               )""",
            (
                str(group_id),
                str(run_id),
                match_id,
                model_version_id,
                payload["play_type"],
                payload["market_variant"],
                payload["predict_time"],
                Json(payload["expected_options"]),
                Json(payload["probability_vector"]),
                Json(payload["score_matrix"]) if payload["score_matrix"] is not None else None,
                Json(payload["odds_snapshot_ids"]),
                Json(payload["odds_snapshot_times"]),
                payload["feature_snapshot_id"],
                None,
                None,
                Json(payload["output_manifest"]),
                psycopg2.Binary(payload["output_manifest_canonical"]),
                payload["provenance_status"],
                payload["output_sha256"],
            ),
        )
    for ordinal, prediction in enumerate(payload["predictions"]):
        prediction_id = store_model_prediction(conn, dict(prediction), commit=False)
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_prediction_group_options
                       (group_id, option_code, prediction_id, ordinal)
                   VALUES (%s, %s, %s, %s)""",
                (str(group_id), prediction["option_code"], prediction_id, ordinal),
            )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute(
            """UPDATE model_prediction_groups
               SET group_status='complete', completed_at=clock_timestamp()
               WHERE id=%s""",
            (str(group_id),),
        )

    option_conn = psycopg2.connect(os.environ["FQP_P106_TEST_DATABASE_URL"])
    try:
        with option_conn.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            cursor.execute("SET lock_timeout = '150ms'")
            cursor.execute(
                """INSERT INTO model_predictions (
                       match_id, model_version_id, predict_time, play_type, option_code,
                       model_probability, validation_status, calculation_version
                   ) VALUES (%s, %s, '2026-10-23T10:00:00', 'spf', 'X', 0.01,
                             'valid', 'test-v1') RETURNING id""",
                (match_id, model_version_id),
            )
            extra_prediction_id = cursor.fetchone()[0]
        option_conn.commit()
        with pytest.raises(LockNotAvailable):
            with option_conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO model_prediction_group_options
                           (group_id, option_code, prediction_id, ordinal)
                       VALUES (%s, 'X', %s, 3)""",
                    (str(group_id), extra_prediction_id),
                )
        option_conn.rollback()

        conn.commit()
        with pytest.raises(RaiseException, match="completed prediction groups are immutable"):
            with option_conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO model_prediction_group_options
                           (group_id, option_code, prediction_id, ordinal)
                       VALUES (%s, 'X', %s, 3)""",
                    (str(group_id), extra_prediction_id),
                )
        option_conn.rollback()
        with pytest.raises(RaiseException, match="prediction group option mappings are immutable"):
            with conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE model_prediction_group_options
                       SET group_id=%s WHERE group_id=%s AND option_code='3'""",
                    (str(group_id), str(group_id)),
                )
        conn.rollback()
    finally:
        option_conn.close()


def test_option_insert_serializes_against_unmapped_prediction_update(isolated_database):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json

    from scripts.model_prediction_run_storage import (
        build_prediction_group_payload,
        create_prediction_run,
    )
    from scripts.model_storage import store_model_prediction

    conn, schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-option-prediction-update-lock",
        code_fingerprint={"sha256": "d" * 64},
        model_manifest=[],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )

    metadata = {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": "spf",
        "market_variant": "",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["X"],
        "odds_snapshot_ids": {"X": 44},
        "feature_snapshot_id": 77,
    }
    payload = build_prediction_group_payload(
        run_id=run_id,
        metadata=metadata,
        predictions=[
            {
                "match_id": match_id,
                "model_version_id": model_version_id,
                "odds_snapshot_id": 44,
                "feature_snapshot_id": 77,
                "predict_time": metadata["predict_time"],
                "play_type": "spf",
                "option_code": "X",
                "model_probability": 0.5,
                "market_probability": 0.5,
                "break_even_probability": 0.5,
                "market_edge": 0.0,
                "breakeven_edge": 0.0,
                "ev": 0.0,
                "validation_status": "valid",
                "calculation_version": "test-v1",
            }
        ],
    )
    group_id = uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO model_prediction_groups (
                   id, run_id, match_id, model_version_id, play_type, market_variant,
                   predict_time, expected_options, probability_vector, score_matrix,
                   odds_snapshot_ids, odds_snapshot_times, feature_snapshot_id,
                   input_fence, artifact_identity, output_manifest, output_manifest_canonical,
                   provenance_status, output_sha256, group_status
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   %s, %s, 'building'
               )""",
            (
                str(group_id),
                str(run_id),
                match_id,
                model_version_id,
                payload["play_type"],
                payload["market_variant"],
                payload["predict_time"],
                Json(payload["expected_options"]),
                Json(payload["probability_vector"]),
                None,
                Json(payload["odds_snapshot_ids"]),
                Json(payload["odds_snapshot_times"]),
                payload["feature_snapshot_id"],
                None,
                None,
                Json(payload["output_manifest"]),
                psycopg2.Binary(payload["output_manifest_canonical"]),
                payload["provenance_status"],
                payload["output_sha256"],
            ),
        )
    prediction_id = store_model_prediction(conn, dict(payload["predictions"][0]), commit=False)
    conn.commit()

    update_conn = psycopg2.connect(os.environ["FQP_P106_TEST_DATABASE_URL"])
    option_conn = psycopg2.connect(os.environ["FQP_P106_TEST_DATABASE_URL"])
    try:
        for other_conn in (update_conn, option_conn):
            with other_conn.cursor() as cursor:
                cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            other_conn.commit()
        with update_conn.cursor() as cursor:
            cursor.execute(
                "UPDATE model_predictions SET model_probability=0.9 WHERE id=%s",
                (prediction_id,),
            )

        with option_conn.cursor() as cursor:
            cursor.execute("SET lock_timeout = '150ms'")
        option_conn.commit()
        with pytest.raises(LockNotAvailable):
            with option_conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO model_prediction_group_options
                           (group_id, option_code, prediction_id, ordinal)
                       VALUES (%s, 'X', %s, 0)""",
                    (str(group_id), prediction_id),
                )
        option_conn.rollback()
        update_conn.commit()

        with option_conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_prediction_group_options
                       (group_id, option_code, prediction_id, ordinal)
                   VALUES (%s, 'X', %s, 0)""",
                (str(group_id), prediction_id),
            )
        option_conn.commit()

        with pytest.raises(
            RaiseException,
            match="prediction group vector does not match mapped prediction rows",
        ):
            with conn.cursor() as cursor:
                cursor.execute(
                    """UPDATE model_prediction_groups
                       SET group_status='complete', completed_at=clock_timestamp()
                       WHERE id=%s""",
                    (str(group_id),),
                )
        conn.rollback()
    finally:
        update_conn.close()
        option_conn.close()


def test_run_group_and_finalization_operations_serialize_on_parent_run(isolated_database):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json

    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
    )

    conn, schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-run-group-serialization",
        code_fingerprint={"sha256": "1" * 64},
        model_manifest=[],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )

    group_conn = psycopg2.connect(os.environ["FQP_P106_TEST_DATABASE_URL"])
    try:
        with group_conn.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
        group_conn.commit()
        with group_conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_prediction_groups (
                       id, run_id, match_id, model_version_id, play_type, market_variant,
                       predict_time, expected_options, probability_vector, odds_snapshot_ids,
                       odds_snapshot_times, output_manifest, output_manifest_canonical,
                       provenance_status, output_sha256, group_status, created_at
                   ) VALUES (
                       %s, %s, %s, %s, 'spf', '', '2026-10-23T10:00:00',
                       %s, %s, %s, %s, %s, %s, 'incomplete', %s, 'building', clock_timestamp()
                   )""",
                (
                    str(uuid.uuid4()),
                    str(run_id),
                    match_id,
                    model_version_id,
                    Json(["0", "1", "3"]),
                    Json({}),
                    Json({}),
                    Json({}),
                    Json({}),
                    psycopg2.Binary(b"{}"),
                    hashlib.sha256(b"{}").hexdigest(),
                ),
            )

        with conn.cursor() as cursor:
            cursor.execute("SET lock_timeout = '150ms'")
        conn.commit()
        try:
            with pytest.raises(LockNotAvailable):
                with conn.cursor() as cursor:
                    cursor.execute(
                        "UPDATE model_prediction_runs SET input_manifest=%s WHERE id=%s",
                        (Json({"changed": True}), str(run_id)),
                    )
        finally:
            conn.rollback()
        group_conn.rollback()

        with group_conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM model_prediction_runs WHERE id=%s FOR UPDATE",
                (str(run_id),),
            )
        try:
            with pytest.raises(LockNotAvailable):
                finalize_prediction_run(
                    conn,
                    run_id=run_id,
                    run_status="completed",
                    output_summary={
                        "expected_groups": 1,
                        "completed_groups": 1,
                        "skipped_groups": 0,
                        "missing_groups": [],
                        "input_updates_skipped": 0,
                        "completion_reason": "one_expected_group",
                    },
                )
        finally:
            conn.rollback()
        group_conn.commit()
    finally:
        group_conn.close()


@pytest.mark.parametrize(
    ("attack", "error_pattern"),
    [
        ("wrong_digest", "prediction output manifest SHA-256 does not match content"),
        ("predict_time", "prediction output manifest does not match its group"),
        (
            "market_probability",
            "prediction output manifest options do not match stored rows",
        ),
    ],
)
def test_prediction_group_publication_checks_all_manifest_fields(
    isolated_database, attack, error_pattern
):
    from psycopg2 import Binary
    from psycopg2.extras import Json

    from scripts.model_prediction_run_identity import canonical_json_bytes, content_sha256
    from scripts.model_prediction_run_storage import (
        build_prediction_group_payload,
        create_prediction_run,
    )
    from scripts.model_storage import store_model_prediction

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-output-hash",
        code_fingerprint={"sha256": "e" * 64},
        model_manifest=[],
        input_manifest={},
        provenance_status="incomplete",
    )
    metadata = {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": "spf",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["3", "1", "0"],
        "feature_snapshot_id": 77,
        "odds_snapshot_ids": {"3": 10, "1": 11, "0": 12},
        "odds_snapshot_times": {},
    }
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "odds_snapshot_id": index + 10,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "calculation_version": "test-v1",
        }
        for index, (option, probability) in enumerate((("3", 0.5), ("1", 0.25), ("0", 0.25)))
    ]
    payload = build_prediction_group_payload(
        run_id=run_id,
        metadata=metadata,
        predictions=predictions,
    )
    assert payload["output_sha256"] == content_sha256(payload["output_manifest"])
    if attack == "predict_time":
        payload["output_manifest"]["predict_time"] = "2026-10-23T11:00:00"
        payload["output_manifest_canonical"] = canonical_json_bytes(payload["output_manifest"])
        payload["output_sha256"] = content_sha256(payload["output_manifest"])
    elif attack == "market_probability":
        payload["output_manifest"]["prediction_outputs"][0]["market_probability"] = 0.99
        payload["output_manifest_canonical"] = canonical_json_bytes(payload["output_manifest"])
        payload["output_sha256"] = content_sha256(payload["output_manifest"])
    elif attack == "wrong_digest":
        payload["output_sha256"] = "f" * 64
    group_id = uuid.uuid4()
    with conn.cursor() as cursor:
        cursor.execute(
            """INSERT INTO model_prediction_groups (
                   id, run_id, match_id, model_version_id, play_type, market_variant,
                   predict_time, expected_options, probability_vector, score_matrix,
                   odds_snapshot_ids, odds_snapshot_times, feature_snapshot_id,
                   input_fence, artifact_identity, output_manifest, output_manifest_canonical,
                   provenance_status, output_sha256, group_status
               ) VALUES (
                   %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                   'building'
               )""",
            (
                str(group_id),
                str(run_id),
                match_id,
                model_version_id,
                "spf",
                "",
                payload["predict_time"],
                Json(payload["expected_options"]),
                Json(payload["probability_vector"]),
                None,
                Json(payload["odds_snapshot_ids"]),
                Json(payload["odds_snapshot_times"]),
                payload["feature_snapshot_id"],
                None,
                None,
                Json(payload["output_manifest"]),
                Binary(payload["output_manifest_canonical"]),
                "incomplete",
                payload["output_sha256"],
            ),
        )
    for ordinal, prediction in enumerate(payload["predictions"]):
        prediction_id = store_model_prediction(conn, dict(prediction), commit=False)
        with conn.cursor() as cursor:
            cursor.execute(
                """INSERT INTO model_prediction_group_options
                       (group_id, option_code, prediction_id, ordinal)
                   VALUES (%s, %s, %s, %s)""",
                (str(group_id), prediction["option_code"], prediction_id, ordinal),
            )

    with pytest.raises(RaiseException, match=error_pattern):
        with conn.cursor() as cursor:
            cursor.execute(
                """UPDATE model_prediction_groups
                   SET group_status='complete', completed_at=clock_timestamp()
                   WHERE id=%s""",
                (str(group_id),),
            )
    conn.rollback()


def test_complete_artifact_group_inherits_incomplete_parent_provenance(isolated_database):
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_loader import load_latest_prediction_group
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher_poisson') RETURNING id"
        )
        incomplete_model_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        complete_model_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]

    incomplete_model_identity = {
        "model_version_id": incomplete_model_id,
        "model_name": "maher_poisson",
        "provenance_status": "incomplete",
        "parameters_sha256": "1" * 64,
        "artifact": None,
        "reason": "training_manifest_identity_missing",
    }
    complete_model_identity = {
        "model_version_id": complete_model_id,
        "model_name": "market_baseline",
        "provenance_status": "complete",
        "parameters_sha256": "2" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 2,
            "sha256": "2" * 64,
        },
        "reason": None,
    }
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-incomplete-parent-provenance",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[incomplete_model_identity, complete_model_identity],
        input_manifest={"match_ids": [match_id]},
        provenance_status="incomplete",
    )
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": complete_model_id,
            "odds_snapshot_id": 30 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "raw_model_probability": probability,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "validation_errors": [],
            "calculation_version": "incomplete-parent-provenance-test",
        }
        for index, (option, probability) in enumerate((("3", 0.5), ("1", 0.25), ("0", 0.25)))
    ]

    store_prediction_group(
        conn,
        run_id=run_id,
        metadata={
            "match_id": match_id,
            "model_version_id": complete_model_id,
            "play_type": "spf",
            "market_variant": "",
            "predict_time": "2026-10-23T10:00:00",
            "expected_options": ["3", "1", "0"],
            "odds_snapshot_ids": {"3": 30, "1": 31, "0": 32},
            "artifact_identity": complete_model_identity,
            "provenance_status": "complete",
        },
        predictions=predictions,
    )
    finalize_prediction_run(
        conn,
        run_id=run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )

    loaded = load_latest_prediction_group(
        conn,
        match_id=match_id,
        model_version_id=complete_model_id,
        play_type="spf",
    )
    assert loaded["status"] == "complete", loaded
    assert loaded["provenance_status"] == "incomplete"
    assert loaded["run_provenance_status"] == "incomplete"
    assert len(loaded["options"]) == 3


def test_prediction_group_artifact_must_match_parent_run_manifest(isolated_database):
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        store_prediction_group,
    )

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('market_baseline') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    recorded_identity = {
        "model_version_id": model_version_id,
        "model_name": "market_baseline",
        "provenance_status": "complete",
        "parameters_sha256": "a" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 1,
            "sha256": "a" * 64,
        },
    }
    forged_identity = {**recorded_identity, "parameters_sha256": "b" * 64}
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-artifact-binding",
        code_fingerprint={"sha256": "e" * 64},
        model_manifest=[recorded_identity],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
    )
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "odds_snapshot_id": 10 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "model_probability": probability,
            "market_probability": probability,
            "break_even_probability": probability,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "validation_errors": [],
            "calculation_version": "artifact-binding-test",
        }
        for index, (option, probability) in enumerate((("3", 0.5), ("1", 0.25), ("0", 0.25)))
    ]

    with pytest.raises(RaiseException, match="artifact identity does not match parent run"):
        store_prediction_group(
            conn,
            run_id=run_id,
            metadata={
                "match_id": match_id,
                "model_version_id": model_version_id,
                "play_type": "spf",
                "predict_time": "2026-10-23T10:00:00",
                "expected_options": ["3", "1", "0"],
                "artifact_identity": forged_identity,
                "provenance_status": "complete",
            },
            predictions=predictions,
        )
    conn.rollback()


def test_research_loader_marks_ambiguous_team_name_without_choosing_id(isolated_database):
    from datetime import date, datetime

    from scripts.backtest_engine import load_research_matches

    conn, _schema_name = isolated_database
    kickoff = datetime(2025, 1, 1, 20, 0)
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO teams (team_name_cn) VALUES ('Same Name') RETURNING id")
        first_team_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO teams (team_name_cn) VALUES ('Same Name') RETURNING id")
        second_team_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO teams (team_name_cn) VALUES ('Opponent')")
        cursor.execute(
            """INSERT INTO official_matches (
                   business_date, kickoff_time, home_team_name, away_team_name
               ) VALUES (%s, %s, 'Same Name', 'Opponent') RETURNING id""",
            (date(2025, 1, 1), kickoff),
        )
        match_id = cursor.fetchone()[0]
        cursor.execute(
            """INSERT INTO official_results (
                   match_id, full_home_goals, full_away_goals, result_status
               ) VALUES (%s, 1, 0, 'final')""",
            (match_id,),
        )
    conn.commit()

    matches = load_research_matches(conn, max_matches=1)

    assert matches[0].candidate.home_team_id is None
    assert matches[0].team_identity["home"]["team_name"] == "Same Name"
    assert matches[0].team_identity["home"]["selected_team_id"] is None
    assert matches[0].team_identity["home"]["name_match_count"] == 2
    assert matches[0].team_identity["home"]["candidate_team_ids"] == [
        first_team_id,
        second_team_id,
    ]


def test_failed_group_rolls_back_prediction_and_option_rows(isolated_database):
    from scripts.model_prediction_run_storage import create_prediction_run, store_prediction_group

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher_poisson') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]
    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-release",
        code_fingerprint={"sha256": "b" * 64},
        model_manifest=[],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
    )
    metadata = {
        "match_id": match_id,
        "model_version_id": model_version_id,
        "play_type": "spf",
        "predict_time": "2026-10-23T10:00:00",
        "expected_options": ["3", "1", "0"],
    }
    predictions = [
        {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "odds_snapshot_id": 40 + index,
            "feature_snapshot_id": 77,
            "predict_time": "2026-10-23T10:00:00",
            "play_type": "spf",
            "option_code": option,
            "model_probability": 0.5,
            "market_probability": 0.5,
            "break_even_probability": 0.5,
            "market_edge": 0.0,
            "breakeven_edge": 0.0,
            "ev": 0.0,
            "validation_status": "valid",
            "calculation_version": "test-v1",
        }
        for index, option in enumerate(("3", "1", "0"))
    ]
    predictions[-1]["calculation_version"] = "x" * 65

    with pytest.raises(StringDataRightTruncation):
        store_prediction_group(conn, run_id=run_id, metadata=metadata, predictions=predictions)

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM model_prediction_groups WHERE run_id=%s", (str(run_id),)
        )
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT COUNT(*) FROM model_predictions WHERE match_id=%s", (match_id,))
        assert cursor.fetchone()[0] == 0


def test_research_evaluation_reads_one_bounded_snapshot_and_stores_outside_predictions(
    isolated_database,
):
    from datetime import date, datetime, time, timedelta

    from psycopg2.errors import RaiseException

    from scripts.backtest_engine import (
        ResearchEvaluationConfig,
        evaluate_research_reconstruction,
        load_research_matches,
        store_research_evaluation_run,
    )

    conn, _schema_name = isolated_database
    fixtures = (("Alpha", "Bravo"), ("Bravo", "Charlie"), ("Charlie", "Alpha"))
    with conn.cursor() as cursor:
        for team_name in ("Alpha", "Bravo", "Charlie"):
            cursor.execute("INSERT INTO teams (team_name_cn) VALUES (%s)", (team_name,))
        cursor.execute("SELECT COUNT(*) FROM model_predictions")
        predictions_before = cursor.fetchone()[0]
        for day_index in range(30):
            business_date = date(2025, 1, 1) + timedelta(days=day_index)
            for fixture_index, (home_name, away_name) in enumerate(fixtures):
                kickoff = datetime.combine(business_date, time(20, 0))
                home_goals = (day_index + fixture_index) % 3
                away_goals = (day_index * 2 + fixture_index) % 2
                actual = (
                    "3" if home_goals > away_goals else "1" if home_goals == away_goals else "0"
                )
                cursor.execute(
                    """INSERT INTO official_matches (
                           business_date, kickoff_time, match_status,
                           home_team_name, away_team_name
                       ) VALUES (%s, %s, 'Settled', %s, %s) RETURNING id""",
                    (business_date, kickoff, home_name, away_name),
                )
                match_id = cursor.fetchone()[0]
                cursor.execute(
                    """INSERT INTO official_results (
                           match_id, official_publish_time, full_home_goals,
                           full_away_goals, result_status, spf_result
                       ) VALUES (%s, %s, %s, %s, 'final', %s)""",
                    (match_id, kickoff + timedelta(hours=3), home_goals, away_goals, actual),
                )
                for option, odds in (("h", 2.1), ("d", 3.2), ("a", 3.7)):
                    for snapshot_offset in (70, 10):
                        cursor.execute(
                            """INSERT INTO official_odds_snapshots (
                                   match_id, play_type, option_code, sp_value,
                                   snapshot_time, is_open
                               ) VALUES (%s, 'spf', %s, %s, %s, true)""",
                            (
                                match_id,
                                option,
                                odds + snapshot_offset / 100,
                                kickoff - timedelta(minutes=snapshot_offset),
                            ),
                        )
    conn.commit()

    materialized = load_research_matches(
        conn,
        max_matches=100,
        prediction_lead_minutes=60,
    )
    assert len(materialized) == 90
    assert materialized[0].odds_by_option == {"3": 2.8, "1": 3.9, "0": 4.4}
    assert conn.get_transaction_status() == 0  # TRANSACTION_STATUS_IDLE

    report = evaluate_research_reconstruction(
        materialized,
        ResearchEvaluationConfig(
            fold_count=2,
            test_window_days=5,
            holdout_days=5,
            max_matches=100,
        ),
    )
    run_id = store_research_evaluation_run(conn, report, name="P106-04 local research")
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT config->>'evaluation_mode', config->'final_holdout' FROM backtest_runs WHERE id=%s",
            (run_id,),
        )
        stored_mode, stored_holdout = cursor.fetchone()
        assert stored_mode == "research_reconstruction"
        assert stored_holdout["evaluation_count"] == 1
        cursor.execute("SELECT COUNT(*) FROM model_predictions")
        assert cursor.fetchone()[0] == predictions_before
    conn.commit()

    with conn.cursor() as cursor:
        cursor.execute(
            """CREATE FUNCTION reject_research_completion() RETURNS trigger
               LANGUAGE plpgsql AS $$ BEGIN
                   IF NEW.status='completed' THEN RAISE EXCEPTION 'reject research completion'; END IF;
                   RETURN NEW;
               END $$"""
        )
        cursor.execute(
            """CREATE TRIGGER reject_research_completion
               BEFORE UPDATE OF status ON backtest_runs
               FOR EACH ROW EXECUTE FUNCTION reject_research_completion()"""
        )
    conn.commit()
    with pytest.raises(RaiseException, match="reject research completion"):
        store_research_evaluation_run(conn, report, name="P106-04 rollback probe")
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM backtest_runs WHERE name='P106-04 rollback probe'")
        assert cursor.fetchone()[0] == 0
        cursor.execute("DROP TRIGGER reject_research_completion ON backtest_runs")
        cursor.execute("DROP FUNCTION reject_research_completion()")
    conn.commit()


def test_prediction_replay_uses_only_complete_groups_from_the_requested_run(isolated_database):
    from scripts.backtest_engine import evaluate_prediction_replay
    from scripts.model_prediction_run_identity import content_sha256
    from scripts.model_prediction_run_storage import (
        create_prediction_run,
        finalize_prediction_run,
        store_prediction_group,
    )

    conn, _schema_name = isolated_database
    with conn.cursor() as cursor:
        cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
        first_job_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO model_versions (model_name) VALUES ('maher_poisson') RETURNING id"
        )
        model_version_id = cursor.fetchone()[0]
        match_ids = []
        for day in ("2025-02-01", "2025-02-02"):
            kickoff = f"{day}T20:00:00"
            cursor.execute(
                """INSERT INTO official_matches (
                       business_date, kickoff_time, match_status,
                       home_team_name, away_team_name
                   ) VALUES (%s, %s, 'Settled', 'Alpha', 'Bravo') RETURNING id""",
                (day, kickoff),
            )
            match_id = cursor.fetchone()[0]
            match_ids.append(match_id)
            cursor.execute(
                """INSERT INTO official_results (
                       match_id, official_publish_time, full_home_goals,
                       full_away_goals, result_status, spf_result
                   ) VALUES (%s, %s, 2, 0, 'final', '3')""",
                (match_id, f"{day}T23:00:00"),
            )

    artifact_identity = {
        "model_version_id": model_version_id,
        "model_name": "maher_poisson",
        "provenance_status": "complete",
        "parameters_sha256": "f" * 64,
        "artifact": {
            "kind": "inline_parameters",
            "format": "application/json",
            "size_bytes": 8,
            "sha256": "f" * 64,
        },
        "training_manifest_sha256": "a" * 64,
        "training_identity_sha256": "b" * 64,
    }
    first_run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=first_run_id,
        ai_job_run_id=first_job_id,
        release_id="p106-replay-test",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[artifact_identity],
        input_manifest={"match_ids": match_ids[:1]},
        provenance_status="complete",
    )
    probabilities = {"3": 0.55, "1": 0.25, "0": 0.20}
    market = {"3": 0.50, "1": 0.28, "0": 0.22}

    def store_group(run_id, match_id, predict_time, play_type="spf"):
        metadata = {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "play_type": play_type,
            "predict_time": predict_time,
            "expected_options": ["3", "1", "0"],
            "odds_snapshot_ids": {"3": 1, "1": 2, "0": 3},
            "odds_snapshot_times": {
                "3": "2025-02-01T18:40:00",
                "1": "2025-02-01T18:40:00",
                "0": "2025-02-01T18:40:00",
            },
            "artifact_identity": artifact_identity,
            "provenance_status": "complete",
        }
        predictions = [
            {
                "match_id": match_id,
                "model_version_id": model_version_id,
                "odds_snapshot_id": index + 1,
                "feature_snapshot_id": 77,
                "predict_time": predict_time,
                "play_type": play_type,
                "option_code": option,
                "raw_model_probability": probabilities[option],
                "model_probability": probabilities[option],
                "market_probability": market[option],
                "break_even_probability": market[option],
                "market_edge": probabilities[option] - market[option],
                "breakeven_edge": probabilities[option] - market[option],
                "ev": 0.0,
                "validation_status": "valid",
                "validation_errors": [],
                "calculation_version": "p106-replay-test",
            }
            for index, option in enumerate(("3", "1", "0"))
        ]
        return store_prediction_group(
            conn, run_id=run_id, metadata=metadata, predictions=predictions
        )

    store_group(first_run_id, match_ids[0], "2025-02-01T19:00:00")
    store_group(first_run_id, match_ids[0], "2025-02-01T19:00:00", play_type="rqspf")
    finalize_prediction_run(
        conn,
        run_id=first_run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 2,
            "completed_groups": 2,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )

    cursor = conn.cursor()
    cursor.execute("INSERT INTO ai_job_runs DEFAULT VALUES RETURNING id")
    second_job_id = cursor.fetchone()[0]
    cursor.close()
    other_run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=other_run_id,
        ai_job_run_id=second_job_id,
        release_id="p106-replay-test-other",
        code_fingerprint={"files": {}, "sha256": content_sha256({})},
        model_manifest=[artifact_identity],
        input_manifest={"match_ids": match_ids[1:]},
        provenance_status="complete",
    )
    store_group(other_run_id, match_ids[1], "2025-02-02T19:00:00")
    finalize_prediction_run(
        conn,
        run_id=other_run_id,
        run_status="completed",
        output_summary={
            "expected_groups": 1,
            "completed_groups": 1,
            "skipped_groups": 0,
            "missing_groups": [],
            "input_updates_skipped": 0,
            "completion_reason": "predictions_completed",
        },
    )

    report = evaluate_prediction_replay(conn, str(first_run_id))
    assert report["evaluation_mode"] == "prediction_replay"
    assert report["prediction_run_id"] == str(first_run_id)
    assert report["model_match_ids"] == [match_ids[0]]
    assert report["model_market_match_ids"] == [match_ids[0]]
    assert report["predictions"][0]["output_sha256"]
    assert report["predictions"][0]["artifact_identity"]["provenance_status"] == "complete"
    assert report["sample_count"] == 1
    assert report["excluded"] == [{"match_id": match_ids[0], "reason": "unsupported_play_type"}]
    from scripts.model_prediction_run_loader import load_latest_prediction_group

    loaded = load_latest_prediction_group(
        conn,
        match_id=match_ids[0],
        model_version_id=model_version_id,
        play_type="spf",
    )
    assert loaded["status"] == "complete"


def test_z_down_migration_removes_only_p106_objects(isolated_database):
    conn, _schema_name = isolated_database
    down_path = (
        Path(__file__).resolve().parents[2] / "sql/down/111_prediction_run_identity.down.sql"
    )
    down = down_path.read_text(encoding="utf-8")
    with conn.cursor() as cursor:
        cursor.execute(down)
        cursor.execute(
            "SELECT to_regclass('model_prediction_runs'), to_regclass('model_predictions')"
        )
        run_table, legacy_table = cursor.fetchone()
    assert run_table is None
    assert legacy_table is not None


def test_model_training_manifest_is_recomputable_and_append_only(isolated_database):
    from datetime import datetime

    from scripts.model_training_manifest_storage import (
        load_training_manifest,
        persist_training_manifest,
    )
    from scripts.training_manifest import CandidateMatch, build_training_dataset

    conn, _schema_name = isolated_database
    dataset = build_training_dataset(
        [
            CandidateMatch(
                match_id=101,
                result_id=201,
                kickoff_at=datetime(2025, 1, 1),
                home_team_id=1,
                away_team_id=2,
                home_goals=2,
                away_goals=1,
                match_status="settled",
                official_publish_time=datetime(2025, 1, 1, 20),
            ),
            CandidateMatch(
                match_id=102,
                result_id=202,
                kickoff_at=datetime(2025, 1, 2),
                home_team_id=2,
                away_team_id=1,
                home_goals=0,
                away_goals=0,
                match_status="settled",
                official_publish_time=datetime(2025, 1, 2, 20),
            ),
        ],
        min_matches=1,
    )
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('maher_poisson') RETURNING id")
        model_version_id = cur.fetchone()[0]

    persist_training_manifest(conn, model_version_id, dataset.manifest.to_dict())
    conn.commit()

    assert load_training_manifest(conn, model_version_id) == dataset.manifest.to_dict()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT included_count, excluded_count, training_manifest_sha256, "
            "encode(pg_catalog.sha256(manifest_canonical), 'hex') "
            "FROM model_training_manifests WHERE model_version_id=%s",
            (model_version_id,),
        )
        included_count, excluded_count, manifest_sha256, content_sha256 = cur.fetchone()
    assert included_count == 2
    assert excluded_count == 0
    assert manifest_sha256 == dataset.manifest.sha256
    assert content_sha256

    with conn.cursor() as cur, pytest.raises(RaiseException, match="immutable"):
        cur.execute(
            "UPDATE model_training_manifests SET manifest_json='{}'::jsonb "
            "WHERE model_version_id=%s",
            (model_version_id,),
        )
    conn.rollback()
    with conn.cursor() as cur, pytest.raises(RaiseException, match="immutable"):
        cur.execute(
            "DELETE FROM model_training_manifests WHERE model_version_id=%s",
            (model_version_id,),
        )
    conn.rollback()


def test_model_training_manifest_preserves_old_versions_without_backfill(isolated_database):
    conn, _schema_name = isolated_database
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('maher_poisson') RETURNING id")
        old_model_version_id = cur.fetchone()[0]
        cur.execute(
            "SELECT COUNT(*) FROM model_training_manifests WHERE model_version_id=%s",
            (old_model_version_id,),
        )
        assert cur.fetchone()[0] == 0


def _sample_persisted_training_manifest():
    from datetime import datetime

    from scripts.training_manifest import CandidateMatch, build_training_dataset

    dataset = build_training_dataset(
        [
            CandidateMatch(
                match_id=301,
                result_id=401,
                kickoff_at=datetime(2025, 3, 1),
                home_team_id=1,
                away_team_id=2,
                home_goals=1,
                away_goals=0,
                match_status="settled",
                official_publish_time=datetime(2025, 3, 1, 20),
            )
        ],
        min_matches=1,
    )
    return dataset.manifest.to_dict()


def test_model_training_manifest_loader_rejects_noncanonical_persisted_bytes(isolated_database):
    from psycopg2 import Binary

    from scripts.model_training_manifest_storage import (
        load_training_manifest,
        persist_training_manifest,
    )

    conn, _schema_name = isolated_database
    manifest = _sample_persisted_training_manifest()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('maher_poisson') RETURNING id")
        model_version_id = cur.fetchone()[0]
    persist_training_manifest(conn, model_version_id, manifest)
    conn.commit()

    trailing_space = Binary(b" ")
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE model_training_manifests "
            "DISABLE TRIGGER trg_model_training_manifest_immutable"
        )
        cur.execute(
            """UPDATE model_training_manifests
               SET manifest_canonical = manifest_canonical || %s,
                   content_sha256 = encode(
                       pg_catalog.sha256(manifest_canonical || %s), 'hex'
                   )
               WHERE model_version_id = %s""",
            (trailing_space, trailing_space, model_version_id),
        )
        cur.execute(
            "ALTER TABLE model_training_manifests "
            "ENABLE TRIGGER trg_model_training_manifest_immutable"
        )
    conn.commit()

    with pytest.raises(ValueError, match="identity fields do not match content"):
        load_training_manifest(conn, model_version_id)


def test_model_training_manifest_fqp_role_can_insert_and_select_but_not_mutate(
    isolated_database,
):
    from psycopg2 import sql
    from psycopg2.errors import InsufficientPrivilege

    from scripts.model_training_manifest_storage import (
        load_training_manifest,
        persist_training_manifest,
    )

    conn, schema_name = isolated_database
    manifest = _sample_persisted_training_manifest()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO model_versions(model_name) VALUES ('maher_poisson') RETURNING id")
        model_version_id = cur.fetchone()[0]
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema_name)))
        cur.execute("SET LOCAL ROLE fqp")
        cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name)))

    persist_training_manifest(conn, model_version_id, manifest)
    assert load_training_manifest(conn, model_version_id) == manifest
    conn.commit()

    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
        cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name)))
        with pytest.raises(InsufficientPrivilege, match="permission denied"):
            cur.execute(
                "UPDATE model_training_manifests SET included_count=0 WHERE model_version_id=%s",
                (model_version_id,),
            )
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
        cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema_name)))
        with pytest.raises(InsufficientPrivilege, match="permission denied"):
            cur.execute(
                "DELETE FROM model_training_manifests WHERE model_version_id=%s",
                (model_version_id,),
            )
    conn.rollback()


def test_mle_manifest_failure_rolls_back_old_model_deactivation(isolated_database):
    from contextlib import nullcontext
    from datetime import date, datetime
    from unittest.mock import patch

    from scripts.mle_trainer import run
    from scripts.training_manifest import CandidateMatch, build_training_dataset

    conn, _schema_name = isolated_database
    with conn.cursor() as cur:
        cur.execute(
            """ALTER TABLE model_versions
                   ADD COLUMN model_type VARCHAR(64),
                   ADD COLUMN version VARCHAR(64),
                   ADD COLUMN training_start_date DATE,
                   ADD COLUMN training_end_date DATE,
                   ADD COLUMN parameters_json JSONB,
                   ADD COLUMN description TEXT,
                   ADD COLUMN is_active BOOLEAN DEFAULT false,
                   ADD COLUMN created_at TIMESTAMPTZ DEFAULT now()"""
        )
        cur.execute(
            """INSERT INTO model_versions(model_name, is_active)
               VALUES ('maher_poisson', true), ('dixon_coles', true)"""
        )
        cur.execute(
            """CREATE FUNCTION reject_training_manifest_for_test()
               RETURNS TRIGGER LANGUAGE plpgsql AS $$
               BEGIN RAISE EXCEPTION 'test manifest insert failure'; END;
               $$"""
        )
        cur.execute(
            """CREATE TRIGGER reject_training_manifest_for_test
               BEFORE INSERT ON model_training_manifests
               FOR EACH ROW EXECUTE FUNCTION reject_training_manifest_for_test()"""
        )
    conn.commit()

    dataset = build_training_dataset(
        [
            CandidateMatch(
                match_id=101,
                result_id=201,
                kickoff_at=datetime(2025, 1, 1),
                home_team_id=1,
                away_team_id=2,
                home_goals=2,
                away_goals=1,
                match_status="settled",
                official_publish_time=datetime(2025, 1, 1, 20),
            ),
            CandidateMatch(
                match_id=102,
                result_id=202,
                kickoff_at=datetime(2025, 1, 2),
                home_team_id=2,
                away_team_id=1,
                home_goals=0,
                away_goals=0,
                match_status="settled",
                official_publish_time=datetime(2025, 1, 2, 20),
            ),
        ],
        min_matches=1,
    )
    trained = {
        "maher_poisson": {
            "attack": {1: 0.1, 2: -0.1},
            "defense": {1: -0.1, 2: 0.1},
            "home_advantage": 0.2,
            "league_intercept": 0.4,
            "n_matches": 2,
            "n_teams": 2,
            "nll": 1.0,
            "converged": True,
            "training_start_date": date(2025, 1, 1),
            "training_end_date": date(2025, 1, 2),
            "training_manifest": dataset.manifest.to_dict(),
        },
        "dixon_coles_rho": {"rho": -0.08, "nll": 1.0, "n_low_score_matches": 2},
    }

    with (
        patch("apps.backend.src.db.get_db", return_value=nullcontext(conn)),
        patch("scripts.mle_trainer.fit_all_models", return_value=trained),
        pytest.raises(RaiseException, match="test manifest insert failure"),
    ):
        run()
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SELECT model_name, is_active FROM model_versions ORDER BY model_name")
        model_rows = cur.fetchall()
        cur.execute("SELECT count(*) FROM model_training_manifests")
        manifest_count = cur.fetchone()[0]
    assert model_rows == [("dixon_coles", True), ("maher_poisson", True)]
    assert manifest_count == 0
