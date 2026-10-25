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
        assert cursor.fetchall() == [("completed",), ("failed",), ("failed",), ("completed",)]


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
@pytest.mark.parametrize("read_kind", ["recent", "summary"])
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
    capture = MagicMock()
    captured_cursor = capture.cursor.return_value.__enter__.return_value
    captured_cursor.fetchall.return_value = []
    captured_cursor.fetchone.return_value = (0, 0, None, 0, None)
    monkeypatch.setattr(router, "get_db", lambda: nullcontext(capture))
    router.list_predictions(match_id=None, limit=200, include_summary=True)
    summary_query, summary_params = captured_cursor.execute.call_args.args
    with conn.cursor() as cursor:
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
    if read_kind == "summary":
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
        if read_kind == "summary":
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
        if read_kind == "summary":
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
            cursor.execute(
                sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema))
            )
            cursor.execute(
                sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(
                    sql.Identifier(schema)
                )
            )
        cursor.execute("ANALYZE")
    conn.commit()
    if read_kind == "summary":
        with conn.cursor() as cursor:
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
        router.list_predictions(
            match_id=match_id, limit=limit, include_summary=read_kind == "summary"
        )
        query, params = captured_cursor.execute.call_args.args
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            actual = cursor.fetchall()
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
            if read_kind == "summary":
                confidence = [row[3] for row in eligible if row[3] is not None]
                expected = (
                    len(eligible),
                    sum(row[2] is not None and row[2] > 0 for row in eligible),
                    sum(confidence) / len(confidence) if confidence else None,
                    len({row[4] for row in eligible}),
                    max((row[1] for row in eligible), default=None),
                )
                assert len(actual) == 1
                assert actual[0][:2] == expected[:2]
                if confidence:
                    assert actual[0][2] == pytest.approx(expected[2])
                else:
                    assert actual[0][2] is None
                assert actual[0][3:] == expected[3:]
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
                assert len(cursor.fetchall()) == (1 if read_kind == "summary" else 200)
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
            SELECT '2026-10-25 18:00'::timestamp FROM generate_series(1,100)""")
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
    conn.commit()

    capture = MagicMock()
    capture.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    monkeypatch.setattr(router, "get_db", lambda: nullcontext(capture))
    router.get_prediction_model_overview()
    query, params = capture.cursor.return_value.__enter__.return_value.execute.call_args.args

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

    loops = list(windows(plan["Plan"]))
    print(
        json.dumps(
            {
                "fixture_rows": 90000,
                "execution_time_ms": plan["Execution Time"],
                "global_ranking_loops": loops,
            }
        )
    )
    assert loops and max(loops) == 1, "global legacy ranking must not repeat per model"


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
