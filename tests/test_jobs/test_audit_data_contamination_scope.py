from __future__ import annotations

from unittest.mock import MagicMock

from scripts.jobs.audit_data_contamination import _check_error_analysis_scope


def test_error_analysis_scope_only_flags_recent_rows() -> None:
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = []

    assert _check_error_analysis_scope(conn) == []
    query = cur.execute.call_args.args[0]
    assert "pea.created_at >= NOW() - INTERVAL '72 hours'" in query
