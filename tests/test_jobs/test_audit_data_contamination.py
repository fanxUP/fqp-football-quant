from unittest.mock import MagicMock

import pytest

from scripts.jobs import audit_data_contamination as auditor
from scripts.jobs.audit_data_contamination import (
    _check_error_analysis_scope,
    _check_feature_snapshot_staleness,
    _check_odds_temporal_integrity,
    _check_prediction_temporal_integrity,
    _resolve_previous_findings,
)


@pytest.fixture
def audit_run(monkeypatch, mock_conn):
    conn, cursor = mock_conn
    context = MagicMock()
    context.__enter__.return_value = conn
    monkeypatch.setattr(auditor, "get_db", lambda: context)
    checks = {}
    for name in (
        "_check_lineup_temporal_integrity",
        "_check_odds_temporal_integrity",
        "_check_result_leak",
        "_check_feature_snapshot_staleness",
        "_check_prediction_temporal_integrity",
        "_check_error_analysis_scope",
    ):
        checks[name] = MagicMock(return_value=[])
        monkeypatch.setattr(auditor, name, checks[name])
    store = MagicMock()
    resolve = MagicMock()
    monkeypatch.setattr(auditor, "store_contamination_audit", store)
    monkeypatch.setattr(auditor, "_resolve_previous_findings", resolve)
    return conn, cursor, checks, store, resolve


def test_failed_check_is_not_clean_and_does_not_resolve_previous_findings(audit_run):
    _, cursor, checks, store, resolve = audit_run
    checks["_check_lineup_temporal_integrity"].side_effect = ValueError("fixture failure")

    result = auditor._run_impl()

    assert result["status"] == "failed"
    assert result["checks_complete"] is False
    assert result["failed_checks"] == 1
    assert result["total_findings"] == 0
    assert "pre_match_lineup" not in [call.args[1] for call in resolve.call_args_list]
    failed = [
        call.args[1]
        for call in store.call_args_list
        if call.args[1]["check_type"] == "pre_match_lineup"
    ]
    assert len(failed) == 1
    assert failed[0]["evidence"]["check_status"] == "failed"
    assert "no issues found" not in failed[0]["detail"]
    assert failed[0]["evidence"]["error_type"] == "ValueError"
    assert all(check.call_count == 1 for check in checks.values())
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("ROLLBACK TO SAVEPOINT" in sql for sql in statements)


def test_successful_check_keeps_findings_and_records_completion(audit_run):
    _, _, checks, store, resolve = audit_run
    finding = {
        "check_type": "feature_leak",
        "match_id": 12,
        "severity": "critical",
        "contamination_detected": True,
        "detail": "fixture finding",
    }
    checks["_check_feature_snapshot_staleness"].return_value = [finding]

    result = auditor._run_impl()

    assert result["status"] == "ok"
    assert result["checks_complete"] is True
    assert result["critical"] == 1
    writes = [call.args[1] for call in store.call_args_list]
    assert any(item.get("match_id") == 12 and item["contamination_detected"] for item in writes)
    completions = [
        item for item in writes if item.get("evidence", {}).get("check_status") == "passed"
    ]
    assert len(completions) == 6
    assert all(call.kwargs["commit"] is False for call in store.call_args_list)
    assert all(call.kwargs["commit"] is False for call in resolve.call_args_list)


def test_failed_dry_run_reports_unknown_without_persisting(audit_run):
    conn, _, checks, store, resolve = audit_run
    checks["_check_odds_temporal_integrity"].side_effect = RuntimeError("fixture timeout")

    result = auditor._run_impl(dry_run=True)

    assert result["status"] == "dry_run"
    assert result["checks_complete"] is False
    assert result["failed_checks"] == 1
    store.assert_not_called()
    resolve.assert_not_called()
    conn.commit.assert_not_called()


def test_temporal_audits_require_precise_official_kickoff_time(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = []

    _check_odds_temporal_integrity(conn)
    odds_query = cur.execute.call_args.args[0]
    _check_feature_snapshot_staleness(conn)
    feature_query = cur.execute.call_args.args[0]

    assert "NULLIF(m.raw_json->>'matchTime', '') IS NOT NULL" in odds_query
    assert "NULLIF(m.raw_json->>'matchTime', '') IS NOT NULL" in feature_query


def test_new_audit_resolves_previous_findings_for_same_check(mock_conn):
    conn, cur = mock_conn

    _resolve_previous_findings(conn, "feature_leak")

    query, params = cur.execute.call_args.args
    assert "resolved = true" in query
    assert params == ("feature_leak",)
    conn.commit.assert_called_once()


def test_contamination_audit_checks_post_kickoff_predictions(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = []

    _check_prediction_temporal_integrity(conn)

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "FROM model_predictions mp" in query
    assert "mp.predict_time >= m.kickoff_time" in query
    assert "mp.created_at >= NOW() - INTERVAL '2 days'" in query


def test_contamination_audit_checks_error_rows_against_top_prematch_pick(mock_conn):
    conn, cur = mock_conn
    cur.fetchall.return_value = []

    _check_error_analysis_scope(conn)

    query = " ".join(cur.execute.call_args.args[0].split())
    assert "FROM prediction_error_analysis pea" in query
    assert "mp.predict_time < m.kickoff_time" in query
    assert "pick_rank = 1" in query
