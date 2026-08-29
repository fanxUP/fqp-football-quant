from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from scripts.jobs.recovery_storage import (
    claim_recovery_task,
    create_recovery_session,
    finish_recovery_task,
    insert_recovery_task_plan,
    mark_recovery_session,
)


def _conn(fetchone=None, rowcount=1):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchone.return_value = fetchone
    cur.rowcount = rowcount
    return conn, cur


def test_create_recovery_session_is_idempotent_by_boot_id() -> None:
    conn, cur = _conn(fetchone=(7, "planned"))
    result = create_recovery_session(
        conn,
        boot_id="boot-1",
        outage_start=datetime(2026, 8, 28, tzinfo=timezone.utc),
        outage_end=datetime(2026, 8, 29, tzinfo=timezone.utc),
        mode="plan",
    )

    assert result == {"id": 7, "status": "planned"}
    query, params = cur.execute.call_args.args
    assert "ON CONFLICT (boot_id) DO NOTHING" in query
    assert params["boot_id"] == "boot-1"
    conn.commit.assert_called_once()


def test_task_plan_uses_stable_idempotency_key() -> None:
    conn, cur = _conn(rowcount=1)
    inserted = insert_recovery_task_plan(
        conn,
        7,
        {
            "task_code": "build_feature_snapshots",
            "business_window_start": datetime(2026, 8, 28, tzinfo=timezone.utc),
            "business_window_end": datetime(2026, 8, 29, tzinfo=timezone.utc),
            "idempotency_key": "7:build_feature_snapshots:2026-08-28",
            "strategy": "each_window",
        },
    )

    assert inserted is True
    query, params = cur.execute.call_args.args
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in query
    assert params["recovery_session_id"] == 7
    assert params["status"] == "planned"
    conn.commit.assert_called_once()


def test_mark_recovery_session_rejects_unknown_status() -> None:
    conn, cur = _conn()
    try:
        mark_recovery_session(conn, 7, "unknown")
    except ValueError as exc:
        assert "Unsupported recovery session status" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    cur.execute.assert_not_called()


def test_claim_recovery_task_locks_and_increments_attempt() -> None:
    conn, cur = _conn()
    cur.fetchone.side_effect = [
        (9, "current_odds", None, None, "latest_only", 0),
        (9, "current_odds", None, None, "latest_only", 1),
    ]

    result = claim_recovery_task(conn, 7)

    assert result == {
        "id": 9,
        "task_code": "current_odds",
        "business_window_start": None,
        "business_window_end": None,
        "strategy": "latest_only",
        "attempt_count": 1,
    }
    assert "FOR UPDATE SKIP LOCKED" in cur.execute.call_args_list[0].args[0]
    conn.commit.assert_called_once()


def test_finish_recovery_task_can_return_to_bounded_retry_queue() -> None:
    conn, cur = _conn(rowcount=1)

    result = finish_recovery_task(
        conn,
        9,
        "planned",
        error="temporary upstream failure",
        next_attempt_at="2026-08-29T08:00:00+00:00",
    )

    assert result is True
    query, params = cur.execute.call_args.args
    assert "status = 'running'" in query
    assert params[0] == "planned"
    assert params[2] == "temporary upstream failure"
    conn.commit.assert_called_once()
