from __future__ import annotations

import copy
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest
from psycopg2.errors import RaiseException, StringDataRightTruncation


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


def test_prediction_groups_publish_atomically_and_are_read_group_first(isolated_database):
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
        model_version_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO official_matches DEFAULT VALUES RETURNING id")
        match_id = cursor.fetchone()[0]

    run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=run_id,
        ai_job_run_id=job_id,
        release_id="test-release",
        code_fingerprint={"sha256": "a" * 64},
        model_manifest=[{"model_version_id": model_version_id}],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
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
    finalize_prediction_run(conn, run_id=run_id, run_status="completed")
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
    create_prediction_run(
        conn,
        run_id=next_run_id,
        ai_job_run_id=next_job_id,
        release_id="test-release-2",
        code_fingerprint={"sha256": "c" * 64},
        model_manifest=[{"model_version_id": model_version_id}],
        input_manifest={"match_ids": [match_id]},
        provenance_status="complete",
    )
    # Two runs at the exact same prediction timestamp must still publish one
    # complete vector based on the run/group tie-breaker.
    next_metadata = {**metadata}
    next_predictions = copy.deepcopy(predictions)
    for row, probability in zip(next_predictions, (0.2, 0.3, 0.5), strict=True):
        row["model_probability"] = probability
        row["raw_model_probability"] = probability
        row["market_probability"] = probability
    next_group_id = store_prediction_group(
        conn,
        run_id=next_run_id,
        metadata=next_metadata,
        predictions=next_predictions,
    )
    finalize_prediction_run(conn, run_id=next_run_id, run_status="partial")

    loaded = load_latest_prediction_group(
        conn, match_id=match_id, model_version_id=model_version_id, play_type="spf"
    )
    assert str(loaded["group_id"]) == str(next_group_id)
    assert str(loaded["group_id"]) != str(group_id)
    assert sorted(row["option_code"] for row in loaded["options"]) == ["0", "1", "3"]
    assert loaded["probability_vector"] == {"0": 0.5, "1": 0.3, "3": 0.2}

    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT output_manifest, output_sha256 FROM model_prediction_groups WHERE id=%s",
            (str(next_group_id),),
        )
        output_manifest, output_sha256 = cursor.fetchone()
        assert content_sha256(output_manifest) == output_sha256
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

    first_run_id = uuid.uuid4()
    create_prediction_run(
        conn,
        run_id=first_run_id,
        ai_job_run_id=first_job_id,
        release_id="p106-replay-test",
        code_fingerprint={"sha256": "d" * 64},
        model_manifest=[{"model_version_id": model_version_id, "model_name": "maher_poisson"}],
        input_manifest={"match_ids": match_ids[:1]},
        provenance_status="complete",
    )
    probabilities = {"3": 0.55, "1": 0.25, "0": 0.20}
    market = {"3": 0.50, "1": 0.28, "0": 0.22}

    def store_group(run_id, match_id, predict_time):
        metadata = {
            "match_id": match_id,
            "model_version_id": model_version_id,
            "play_type": "spf",
            "predict_time": predict_time,
            "expected_options": ["3", "1", "0"],
            "odds_snapshot_ids": {"3": 1, "1": 2, "0": 3},
            "odds_snapshot_times": {
                "3": "2025-02-01T18:40:00",
                "1": "2025-02-01T18:40:00",
                "0": "2025-02-01T18:40:00",
            },
            "artifact_identity": {
                "model_version_id": model_version_id,
                "provenance_status": "complete",
                "parameters_sha256": "f" * 64,
            },
            "provenance_status": "complete",
        }
        predictions = [
            {
                "match_id": match_id,
                "model_version_id": model_version_id,
                "odds_snapshot_id": index + 1,
                "feature_snapshot_id": 77,
                "predict_time": predict_time,
                "play_type": "spf",
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
    finalize_prediction_run(conn, run_id=first_run_id, run_status="completed")

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
        code_fingerprint={"sha256": "e" * 64},
        model_manifest=[{"model_version_id": model_version_id, "model_name": "maher_poisson"}],
        input_manifest={"match_ids": match_ids[1:]},
        provenance_status="complete",
    )
    store_group(other_run_id, match_ids[1], "2025-02-02T19:00:00")
    finalize_prediction_run(conn, run_id=other_run_id, run_status="completed")

    report = evaluate_prediction_replay(conn, str(first_run_id))
    assert report["evaluation_mode"] == "prediction_replay"
    assert report["prediction_run_id"] == str(first_run_id)
    assert report["model_match_ids"] == [match_ids[0]]
    assert report["model_market_match_ids"] == [match_ids[0]]
    assert report["predictions"][0]["output_sha256"]
    assert report["predictions"][0]["artifact_identity"]["provenance_status"] == "complete"


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
