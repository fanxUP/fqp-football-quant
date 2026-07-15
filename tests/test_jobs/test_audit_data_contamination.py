from scripts.jobs.audit_data_contamination import (
    _check_feature_snapshot_staleness,
    _check_odds_temporal_integrity,
    _resolve_previous_findings,
)


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
