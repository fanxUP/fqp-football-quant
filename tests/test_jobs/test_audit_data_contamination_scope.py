from __future__ import annotations

import os
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extensions import parse_dsn
from psycopg2.extras import Json

from scripts.jobs.audit_data_contamination import _check_error_analysis_scope


@pytest.fixture
def audit_pg():
    dsn = os.getenv("FQP_OBSERVATION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Explicit isolated observation database not configured")
    params = parse_dsn(dsn)
    assert params == dict(
        host="127.0.0.1", port="5432", user="fqp_observation_test", dbname="fqp_observation_test"
    )

    with closing(
        psycopg2.connect(
            dsn,
            connect_timeout=3,
            options="-c statement_timeout=5000 -c lock_timeout=500 -c application_name=fqp_error_scope_fixture",
        )
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                "WHERE datname=current_database()"
            )
            assert cur.fetchone() == ("fqp-p104-isolated-fixtures/v1",)
        yield conn
        conn.rollback()


def test_error_analysis_scope_only_flags_recent_rows() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = []

    assert _check_error_analysis_scope(conn) == []
    query = cur.execute.call_args.args[0]
    assert "pea.created_at >= NOW() - INTERVAL '72 hours'" in query


def test_error_analysis_scope_compares_each_prediction_snapshot() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = []

    _check_error_analysis_scope(conn)

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "mp.match_id, mp.model_version_id, mp.predict_time, mp.option_code" in query
    assert "PARTITION BY match_id, model_version_id, predict_time" in query
    assert "AND tp.match_id = e.match_id" in query
    assert "AND tp.model_version_id = e.model_version_id" in query
    assert "AND tp.predict_time = e.predict_time" in query
    assert "mp.validation_status = 'valid'" in query
    assert "mp.uncertainty_reason->'model_independent' = 'true'::jsonb" in query
    assert "error_snapshots es" in query


def test_error_analysis_scope_uses_snapshot_rank_and_flags_bad_links(audit_pg) -> None:
    """Exercise rank flips and invalid links against the isolated PostgreSQL schema."""
    with audit_pg.cursor() as cur:
        cur.execute("SELECT NOW()::timestamp")
        now = cur.fetchone()[0].replace(microsecond=0)
    error_ids: dict[str, int] = {}
    match_counter = 0

    def add_match(tag: str) -> int:
        nonlocal match_counter
        match_counter += 1
        with audit_pg.cursor() as cur:
            cur.execute(
                """INSERT INTO official_matches (
                       business_date, official_match_code, source_match_id,
                       league_name, home_team_name, away_team_name, kickoff_time
                   ) VALUES (%s, %s, %s, 'fixture', %s, '客队', %s)
                   RETURNING id""",
                (
                    now.date(),
                    f"周一{match_counter:03d}",
                    uuid4().hex,
                    tag,
                    now + timedelta(days=7),
                ),
            )
            return cur.fetchone()[0]

    def add_model(tag: str) -> int:
        with audit_pg.cursor() as cur:
            cur.execute(
                """INSERT INTO model_versions (model_name, model_type, version)
                   VALUES (%s, 'fixture', %s) RETURNING id""",
                (f"error-scope-{tag}-{uuid4().hex}", "v1"),
            )
            return cur.fetchone()[0]

    def add_prediction(
        match_id: int,
        model_id: int,
        predict_time: datetime,
        option_code: str,
        probability: float,
        *,
        independent: object = True,
        status: str = "valid",
    ) -> int:
        with audit_pg.cursor() as cur:
            cur.execute(
                """INSERT INTO model_predictions (
                       match_id, model_version_id, predict_time, play_type,
                       option_code, model_probability, uncertainty_reason,
                       validation_status
                   ) VALUES (%s, %s, %s, 'spf', %s, %s, %s, %s)
                   RETURNING id""",
                (
                    match_id,
                    model_id,
                    predict_time,
                    option_code,
                    probability,
                    Json({"model_independent": independent}),
                    status,
                ),
            )
            return cur.fetchone()[0]

    def add_error(
        match_id: int,
        prediction_id: int | None,
        *,
        created_at=None,
        hours_ago: int | None = None,
    ) -> int:
        with audit_pg.cursor() as cur:
            if hours_ago is not None:
                cur.execute(
                    """INSERT INTO prediction_error_analysis (
                           match_id, prediction_id, created_at
                       ) VALUES (%s, %s, NOW() - %s * INTERVAL '1 hour')
                       RETURNING id""",
                    (match_id, prediction_id, hours_ago),
                )
                return cur.fetchone()[0]
            cur.execute(
                """INSERT INTO prediction_error_analysis (
                       match_id, prediction_id, created_at
                   ) VALUES (%s, %s, %s) RETURNING id""",
                (match_id, prediction_id, created_at or now),
            )
            return cur.fetchone()[0]

    # The old snapshot ranks option 3 first; a later forecast reverses that
    # order. A later rank change must not retroactively invalidate the old row.
    match_id = add_match("rank flip")
    model_id = add_model("rank-flip")
    old_time = now - timedelta(hours=3)
    later_time = now - timedelta(hours=2)
    old_top = add_prediction(match_id, model_id, old_time, "3", 0.55)
    old_non_top = add_prediction(match_id, model_id, old_time, "1", 0.30)
    add_prediction(match_id, model_id, old_time, "0", 0.15)
    add_prediction(match_id, model_id, later_time, "3", 0.15)
    add_prediction(match_id, model_id, later_time, "1", 0.60)
    add_prediction(match_id, model_id, later_time, "0", 0.25)
    error_ids["old_top"] = add_error(match_id, old_top)
    error_ids["same_snapshot_non_top"] = add_error(match_id, old_non_top)

    malformed_match = add_match("malformed marker")
    malformed_model = add_model("malformed")
    malformed_time = now - timedelta(hours=1)
    malformed_id = add_prediction(
        malformed_match,
        malformed_model,
        malformed_time,
        "3",
        0.60,
        independent="broken",
    )
    add_prediction(malformed_match, malformed_model, malformed_time, "1", 0.25)
    add_prediction(malformed_match, malformed_model, malformed_time, "0", 0.15)
    error_ids["malformed_marker"] = add_error(malformed_match, malformed_id)

    # A missing link and a link to a prediction for another match are both
    # invalid even though the latter prediction is a valid snapshot top pick.
    missing_match = add_match("missing link")
    error_ids["missing_link"] = add_error(missing_match, None)

    linked_match = add_match("wrong match link")
    linked_model = add_model("wrong-match")
    linked_time = now - timedelta(minutes=30)
    linked_top = add_prediction(linked_match, linked_model, linked_time, "3", 0.60)
    add_prediction(linked_match, linked_model, linked_time, "1", 0.25)
    add_prediction(linked_match, linked_model, linked_time, "0", 0.15)
    wrong_match = add_match("wrong match error")
    error_ids["wrong_match"] = add_error(wrong_match, linked_top)

    invalid_match = add_match("invalid row")
    invalid_model = add_model("invalid")
    invalid_time = now - timedelta(minutes=20)
    invalid_id = add_prediction(
        invalid_match, invalid_model, invalid_time, "3", 0.60, status="invalid"
    )
    add_prediction(invalid_match, invalid_model, invalid_time, "1", 0.25)
    add_prediction(invalid_match, invalid_model, invalid_time, "0", 0.15)
    error_ids["invalid_row"] = add_error(invalid_match, invalid_id)

    old_window_match = add_match("old error")
    old_window_model = add_model("old-window")
    old_window_time = now - timedelta(days=4)
    old_window_top = add_prediction(old_window_match, old_window_model, old_window_time, "3", 0.60)
    old_window_non_top = add_prediction(
        old_window_match, old_window_model, old_window_time, "1", 0.25
    )
    add_prediction(old_window_match, old_window_model, old_window_time, "0", 0.15)
    error_ids["older_than_72h"] = add_error(
        old_window_match,
        old_window_non_top,
        hours_ago=73,
    )
    error_ids["old_window_top"] = add_error(
        old_window_match,
        old_window_top,
        hours_ago=73,
    )

    # A recent analysis may legitimately refer to a prediction snapshot that
    # is older than 72 hours. Snapshot age must not become an audit cutoff.
    old_forecast_match = add_match("recent error with old forecast")
    old_forecast_model = add_model("recent-old-forecast")
    old_forecast_time = now - timedelta(days=4)
    old_forecast_top = add_prediction(
        old_forecast_match, old_forecast_model, old_forecast_time, "3", 0.60
    )
    old_forecast_non_top = add_prediction(
        old_forecast_match, old_forecast_model, old_forecast_time, "1", 0.25
    )
    add_prediction(old_forecast_match, old_forecast_model, old_forecast_time, "0", 0.15)
    error_ids["recent_error_old_forecast"] = add_error(old_forecast_match, old_forecast_non_top)
    error_ids["recent_error_old_forecast_top"] = add_error(old_forecast_match, old_forecast_top)

    boundary_match = add_match("exact 72-hour boundary")
    boundary_model = add_model("72-hour-boundary")
    boundary_time = now - timedelta(hours=1)
    add_prediction(boundary_match, boundary_model, boundary_time, "3", 0.60)
    boundary_non_top = add_prediction(boundary_match, boundary_model, boundary_time, "1", 0.25)
    add_prediction(boundary_match, boundary_model, boundary_time, "0", 0.15)
    error_ids["exact_72h_boundary"] = add_error(boundary_match, boundary_non_top, hours_ago=72)

    findings = _check_error_analysis_scope(audit_pg)
    flagged_ids = {finding["evidence"]["error_id"] for finding in findings}

    assert flagged_ids == {
        error_ids["same_snapshot_non_top"],
        error_ids["malformed_marker"],
        error_ids["missing_link"],
        error_ids["wrong_match"],
        error_ids["invalid_row"],
        error_ids["recent_error_old_forecast"],
        error_ids["exact_72h_boundary"],
    }
    assert error_ids["old_top"] not in flagged_ids
    assert error_ids["older_than_72h"] not in flagged_ids
    assert error_ids["old_window_top"] not in flagged_ids
    assert error_ids["recent_error_old_forecast_top"] not in flagged_ids
