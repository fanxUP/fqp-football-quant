from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from apps.backend.src.routers import dashboard
from scripts import prediction_statistics


def test_dashboard_metadata_uses_business_timezone(monkeypatch):
    monkeypatch.setattr(
        dashboard,
        "business_now",
        lambda: datetime.fromisoformat("2026-07-18T13:30:00+08:00"),
    )

    assert dashboard._meta("view") == {
        "updated_at": "2026-07-18T13:30:00+08:00",
        "source": "view",
    }


@pytest.mark.parametrize("total", [0, 12_556_119])
def test_prediction_count_reads_the_exact_snapshot_without_scanning_history(
    client, mock_conn, total
):
    conn, cur = mock_conn
    now = datetime(2026, 10, 25, 8, tzinfo=UTC)
    snapshot = {
        "scope": prediction_statistics.COUNT_SCOPE,
        "total": total,
        "data_as_of": (now - timedelta(seconds=20)).isoformat(),
        "computed_at": now.isoformat(),
    }
    cur.fetchone.return_value = ({"prediction_count": snapshot}, "completed", now)
    with patch.object(dashboard, "get_db") as get_db:
        get_db.return_value.__enter__.return_value = conn
        response = client.get("/api/dashboard/prediction-count")
    assert response.status_code == 200
    assert response.json() == {
        "total": total,
        "status": "ok",
        "data_as_of": snapshot["data_as_of"],
        "last_success_at": now.isoformat(),
    }
    cur.execute.assert_called_once()
    sql = " ".join(cur.execute.call_args.args[0].split())
    assert "ai_job_runs" in sql
    assert "model_predictions" not in sql
    assert "COUNT(" not in sql
    assert cur.execute.call_args.args[1] == {"job_code": prediction_statistics.JOB_CODE}
    cur.fetchall.assert_not_called()


@pytest.mark.parametrize(
    "attempt,status",
    [
        (None, "pending"),
        ("running", "pending"),
        ("failed", "unavailable"),
        ("completed", "unavailable"),
    ],
)
def test_count_without_a_completed_snapshot_is_unknown(mock_conn, attempt, status):
    conn, cur = mock_conn
    cur.fetchone.return_value = (None, attempt, datetime.now(UTC))
    assert prediction_statistics.get_prediction_count_snapshot(conn) == {
        "total": None,
        "status": status,
        "data_as_of": None,
        "last_success_at": None,
    }


@pytest.mark.parametrize(
    "age_minutes,attempt,status",
    [
        (0, "running", "ok"),
        (45, "completed", "ok"),
        (46, "completed", "stale"),
        (1, "failed", "refresh_failed"),
    ],
)
def test_count_freshness_uses_snapshot_time_and_latest_attempt(
    mock_conn, age_minutes, attempt, status
):
    conn, cur = mock_conn
    now = datetime(2026, 10, 25, 8, tzinfo=UTC)
    as_of = now - timedelta(minutes=age_minutes)
    cur.fetchone.return_value = (
        {
            "prediction_count": {
                "scope": prediction_statistics.COUNT_SCOPE,
                "total": 0,
                "data_as_of": as_of.isoformat(),
                "computed_at": as_of.isoformat(),
            }
        },
        attempt,
        now,
    )
    result = prediction_statistics.get_prediction_count_snapshot(conn)
    assert result == {
        "total": 0,
        "status": status,
        "data_as_of": as_of.isoformat(),
        "last_success_at": as_of.isoformat(),
    }


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "some_other_count"},
        {"total": -1},
        {"total": True},
        {"total": "42"},
        {"data_as_of": "bad-date"},
        {"data_as_of": "2026-10-25T07:00:00"},
        {"data_as_of": "2026-10-25T09:00:00+00:00"},
    ],
)
def test_malformed_count_snapshots_do_not_become_zero(mock_conn, change):
    conn, cur = mock_conn
    now = datetime(2026, 10, 25, 8, tzinfo=UTC)
    snapshot = {
        "scope": prediction_statistics.COUNT_SCOPE,
        "total": 42,
        "data_as_of": "2026-10-25T07:59:00+00:00",
        "computed_at": now.isoformat(),
        **change,
    }
    cur.fetchone.return_value = ({"prediction_count": snapshot}, "completed", now)
    assert prediction_statistics.get_prediction_count_snapshot(conn) == {
        "total": None,
        "status": "unavailable",
        "data_as_of": None,
        "last_success_at": None,
    }


@pytest.mark.parametrize("failure", [False, True])
def test_count_producer_records_failure_and_releases_its_lock(monkeypatch, failure):
    count_conn, audit_conn = MagicMock(), MagicMock()
    count_cur = count_conn.cursor.return_value.__enter__.return_value
    audit_cur = audit_conn.cursor.return_value.__enter__.return_value
    count_cur.fetchone.side_effect = [(True,), (0, datetime.now(UTC), datetime.now(UTC))]
    audit_cur.fetchone.return_value = (77,)
    monkeypatch.setattr(
        prediction_statistics,
        "get_db",
        MagicMock(
            side_effect=[
                nullcontext(count_conn),
                nullcontext(audit_conn),
            ]
        ),
    )
    if failure:

        def fail_count(_):
            raise RuntimeError("injected timeout")

        monkeypatch.setattr(prediction_statistics, "compute_prediction_count", fail_count)
        with pytest.raises(RuntimeError, match="injected timeout"):
            prediction_statistics.refresh_prediction_count()
    else:
        assert prediction_statistics.refresh_prediction_count()["total"] == 0
    count_conn.rollback.assert_called_once()
    finishes = [
        call.args[1]
        for call in audit_cur.execute.call_args_list
        if "UPDATE ai_job_runs" in call.args[0] and isinstance(call.args[1], dict)
    ]
    assert finishes[-1]["status"] == ("failed" if failure else "completed")


def test_count_lock_contention_does_not_recover_or_start_another_job(monkeypatch):
    count_conn = MagicMock()
    count_conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (False,)
    get_db = MagicMock(return_value=nullcontext(count_conn))
    monkeypatch.setattr(prediction_statistics, "get_db", get_db)
    assert prediction_statistics.refresh_prediction_count() == {
        "status": "skipped",
        "reason": "refresh_already_running",
    }
    assert get_db.call_count == 1
    count_conn.rollback.assert_called_once()


@pytest.mark.parametrize("prefix", ["/api", "/api/v1"])
def test_prediction_count_requires_authentication(client, monkeypatch, prefix):
    monkeypatch.setenv("FQP_AUTH_MODE", "session")
    with patch.object(dashboard, "get_db") as get_db:
        response = client.get(f"{prefix}/dashboard/prediction-count")
    assert response.status_code == 401
    get_db.assert_not_called()


def test_prediction_count_does_not_turn_database_failure_into_zero(client):
    with patch.object(dashboard, "get_db", side_effect=RuntimeError("database unavailable")):
        with pytest.raises(RuntimeError, match="database unavailable"):
            client.get("/api/dashboard/prediction-count")
