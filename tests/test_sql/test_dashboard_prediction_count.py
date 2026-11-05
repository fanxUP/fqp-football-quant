"""Exercise the homepage count on PostgreSQL with connection-local fixtures."""

import os
from contextlib import closing, nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import psycopg2
import pytest

from scripts.prediction_statistics import (
    compute_prediction_count,
    get_prediction_count_snapshot,
    get_prediction_summary_snapshot,
)


@pytest.mark.integration
def test_prediction_count_preserves_global_eligibility_without_evidence_joins():
    dsn = os.getenv("FQP_AUDIT_TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not dsn:
        pytest.skip("Requires an explicitly configured isolated test database")
    database = psycopg2.extensions.parse_dsn(dsn).get("dbname", "")
    assert database.endswith("_test") or database.startswith("fqp_audit_test_"), (
        "Only run synthetic fixtures in a test database"
    )
    with closing(psycopg2.connect(dsn)) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE model_versions (id bigint PRIMARY KEY)")
            cur.execute(
                "CREATE TEMP TABLE official_matches (id bigint PRIMARY KEY, kickoff_time timestamp)"
            )
            cur.execute("""CREATE TEMP TABLE model_predictions (
                id bigint PRIMARY KEY, match_id bigint, model_version_id bigint,
                predict_time timestamp, validation_status text, ev numeric)""")

            assert compute_prediction_count(conn)["total"] == 0
            cur.execute("INSERT INTO model_versions VALUES (1), (2)")
            cur.execute("INSERT INTO official_matches VALUES (10, '2026-10-16 20:00')")
            cur.execute("""INSERT INTO model_predictions VALUES
                    (1,10,1,'2026-10-16 19:00','valid',-1),
                    (2,10,2,'2026-10-16 19:00','valid',0),
                    (3,10,1,'2026-10-16 19:00','valid',1),
                    (4,10,1,'2026-10-16 20:00','valid',1),
                    (5,10,1,'2026-10-16 21:00','valid',1),
                    (6,10,1,'2026-10-16 19:00','rejected',1),
                    (7,10,99,'2026-10-16 19:00','valid',1),
                    (8,99,1,'2026-10-16 19:00','valid',1),
                    (9,10,1,NULL,'valid',1),
                    (10,10,1,'2026-10-16 19:00',NULL,1)""")
            assert compute_prediction_count(conn)["total"] == 3
            cur.execute("DELETE FROM model_predictions WHERE id = 2")
            assert compute_prediction_count(conn)["total"] == 2
            cur.execute("UPDATE official_matches SET kickoff_time = '2026-10-16 18:00'")
            assert compute_prediction_count(conn)["total"] == 0


def test_prediction_summary_snapshot_labels_age_and_failed_refresh_without_losing_values():
    from scripts.prediction_statistics import (
        PREDICTION_SUMMARY_SCOPE,
        get_prediction_summary_snapshot,
    )

    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    data_as_of = now - timedelta(hours=1)
    summary = {
        "scope": PREDICTION_SUMMARY_SCOPE,
        "total": 4187,
        "positive_ev_count": 1632,
        "avg_confidence": 0.714,
        "model_count": 19,
        "latest_predict_time": "2026-11-03T10:45:00+00:00",
        "data_as_of": data_as_of.isoformat(),
        "computed_at": data_as_of.isoformat(),
    }
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (
        {"prediction_summary": summary},
        "failed",
        now,
        now - timedelta(minutes=2),
    )

    result = get_prediction_summary_snapshot(conn, now=now)

    assert result["summary"] == {
        "total": 4187,
        "positive_ev_count": 1632,
        "avg_confidence": 0.714,
        "model_count": 19,
        "latest_predict_time": "2026-11-03T10:45:00+00:00",
    }
    assert result["meta"] == {
        "status": "refresh_failed",
        "data_as_of": data_as_of.isoformat(),
        "last_success_at": data_as_of.isoformat(),
        "last_attempt_at": (now - timedelta(minutes=2)).isoformat(),
        "age_seconds": 3600,
        "stale_after_seconds": 2700,
        "is_stale": True,
    }


def test_prediction_summary_snapshot_without_compatible_success_is_unavailable():
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ({"prediction_count": {"total": 1}}, "completed", now, now)

    result = get_prediction_summary_snapshot(conn, now=now)

    assert result["summary"] is None
    assert result["meta"]["status"] == "unavailable"
    assert result["meta"]["data_as_of"] is None


def test_partial_refresh_with_legacy_count_only_snapshot_reports_refreshing():
    from scripts.prediction_statistics import get_prediction_summary_snapshot

    now = datetime(2026, 11, 5, 13, 22, tzinfo=UTC)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (
        {"prediction_count": {"scope": "valid_prematch_history_v1", "total": 14814579}},
        "partial",
        now,
        now - timedelta(seconds=10),
    )

    result = get_prediction_summary_snapshot(conn, now=now)

    assert result == {
        "summary": None,
        "meta": {
            "status": "refreshing",
            "data_as_of": None,
            "last_success_at": None,
            "last_attempt_at": (now - timedelta(seconds=10)).isoformat(),
            "age_seconds": None,
            "stale_after_seconds": 2700,
            "is_stale": True,
        },
    }


def test_prediction_count_snapshot_with_malformed_success_is_unavailable():
    from scripts.prediction_statistics import COUNT_SCOPE, get_prediction_count_snapshot

    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (
        {
            "prediction_count": {
                "scope": COUNT_SCOPE,
                "total": "not-an-integer",
                "data_as_of": now.isoformat(),
                "computed_at": now.isoformat(),
            }
        },
        "completed",
        now,
    )

    result = get_prediction_count_snapshot(conn)

    assert result == {
        "total": None,
        "status": "unavailable",
        "data_as_of": None,
        "last_success_at": None,
    }


def test_prediction_summary_snapshot_with_malformed_success_is_unavailable():
    from scripts.prediction_statistics import (
        PREDICTION_SUMMARY_SCOPE,
        get_prediction_summary_snapshot,
    )

    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = (
        {
            "prediction_summary": {
                "scope": PREDICTION_SUMMARY_SCOPE,
                "total": -1,
                "positive_ev_count": 0,
                "avg_confidence": None,
                "model_count": 0,
                "latest_predict_time": None,
                "data_as_of": now.isoformat(),
                "computed_at": now.isoformat(),
            }
        },
        "completed",
        now,
        now,
    )

    result = get_prediction_summary_snapshot(conn, now=now)

    assert result["summary"] is None
    assert result["meta"]["status"] == "unavailable"


def test_partial_statistics_refresh_keeps_previous_values_and_reports_refreshing():
    now = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
    data_as_of = now - timedelta(minutes=5)
    count = {
        "scope": "valid_prematch_history_v1",
        "total": 4187,
        "data_as_of": data_as_of.isoformat(),
        "computed_at": data_as_of.isoformat(),
    }
    summary = {
        "scope": "canonical_valid_prematch_history_v1",
        "total": 3500,
        "positive_ev_count": 1300,
        "avg_confidence": 0.71,
        "model_count": 19,
        "latest_predict_time": "2026-11-03T10:45:00",
        "data_as_of": data_as_of.isoformat(),
        "computed_at": data_as_of.isoformat(),
    }

    count_conn = MagicMock()
    count_conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        {"prediction_count": count},
        "partial",
        now,
    )
    assert get_prediction_count_snapshot(count_conn)["total"] == 4187
    assert get_prediction_count_snapshot(count_conn)["status"] == "stale"

    summary_conn = MagicMock()
    summary_conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        {"prediction_summary": summary},
        "partial",
        now,
        now - timedelta(minutes=1),
    )
    result = get_prediction_summary_snapshot(summary_conn, now=now)
    assert result["summary"]["total"] == 3500
    assert result["meta"]["status"] == "stale"
    assert result["meta"]["is_stale"] is True


def test_managed_database_without_rollup_migration_skips_full_history_refresh(monkeypatch):
    from scripts import prediction_statistics

    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [(True, False, True), (True,)]
    monkeypatch.setattr(prediction_statistics, "get_db", lambda: nullcontext(conn))
    compute = MagicMock(side_effect=AssertionError("unbounded compatibility query must not run"))
    monkeypatch.setattr(prediction_statistics, "compute_prediction_snapshots", compute)

    result = prediction_statistics.refresh_prediction_count()

    assert result == {"status": "skipped", "reason": "migration_not_applied"}
    compute.assert_not_called()
    conn.rollback.assert_called_once()
