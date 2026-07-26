from scripts.jobs.validate_evidence_chain import _get_prediction_chain


def test_prediction_chain_reads_existing_model_version_column(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (7, 3, 11, "2026-07-15T10:00:00", "elo_rating", "v1", False)

    result = _get_prediction_chain(conn, 7)

    query = cur.execute.call_args.args[0]
    assert "mv.version" in query
    assert "mv.version_number" not in query
    assert result["version"] == "v1"
    assert result["model_version_exists"] is True
    assert result["model_version_is_active"] is False


def test_prediction_chain_marks_missing_joined_model_version(mock_conn):
    conn, cur = mock_conn
    cur.fetchone.return_value = (7, 999, 11, "2026-07-15T10:00:00", None, None, None)

    result = _get_prediction_chain(conn, 7)

    assert result["model_version_exists"] is False
    assert result["model_version_is_active"] is False
