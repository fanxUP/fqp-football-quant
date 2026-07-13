"""Operational statistics must not turn empty samples into green checks."""

from unittest.mock import MagicMock

from scripts.ops_storage import get_contamination_stats, get_evidence_chain_stats


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
    stats = get_contamination_stats(_connection_with_row((0, None, None)))

    assert stats["has_data"] is False
    assert stats["contamination_found"] == 0
