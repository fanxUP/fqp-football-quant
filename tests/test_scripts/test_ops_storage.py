"""Operational statistics must not turn empty samples into green checks."""

from unittest.mock import MagicMock, patch

from scripts.ops_storage import (
    get_contamination_stats,
    get_evidence_chain_stats,
    store_health_snapshot,
)


def test_health_snapshot_defaults_to_utc_audit_time():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [None, [7]]

    with patch(
        "scripts.ops_storage.utc_now_iso",
        return_value="2026-07-22T10:30:00",
    ):
        result = store_health_snapshot(conn, {"snapshot_date": "2026-07-22"})

    assert result == 7
    insert_params = cur.execute.call_args_list[1].args[1]
    assert insert_params["snapshot_time"] == "2026-07-22T10:30:00"


def _connection_with_row(row):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = row
    return conn


def test_empty_evidence_chain_sample_is_no_data():
    stats = get_evidence_chain_stats(_connection_with_row((0, None, 0)))

    assert stats["has_data"] is False
    assert stats["completeness_rate"] is None


def test_empty_contamination_sample_is_no_data():
    conn = _connection_with_row((0, None, None))

    stats = get_contamination_stats(conn)

    assert stats["has_data"] is False
    assert stats["contamination_found"] == 0
    query = conn.cursor.return_value.__enter__.return_value.execute.call_args.args[0]
    assert "DISTINCT ON (check_type, COALESCE(match_id, -1))" in query
    assert "NOT resolved" in query
