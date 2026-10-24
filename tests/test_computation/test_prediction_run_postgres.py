from __future__ import annotations

import copy
import hashlib
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from psycopg2.errors import LockNotAvailable, RaiseException, StringDataRightTruncation


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

    migration_path = Path(__file__).resolve().parents[2] / "sql/111_prediction_run_identity.sql"
    migration = migration_path.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(migration)

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
