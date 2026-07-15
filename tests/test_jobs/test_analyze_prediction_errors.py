from unittest.mock import patch

from scripts.jobs import analyze_prediction_errors


def test_error_analysis_uses_one_latest_prematch_top_pick_per_model(mock_conn):
    conn, cur = mock_conn
    conn.__enter__.return_value = conn
    cur.fetchall.return_value = []

    with patch.object(analyze_prediction_errors, "get_db", return_value=conn):
        result = analyze_prediction_errors.run()

    query = " ".join(cur.execute.call_args.args[0].split())
    assert result["analyzed"] == 0
    assert "mp.predict_time < m.kickoff_time" in query
    assert "r.result_status IN ('final', 'confirmed')" in query
    assert "DISTINCT ON (" in query
    assert "mp.match_id, mp.model_version_id, mp.option_code" in query
    assert "ROW_NUMBER() OVER" in query
    assert "pick_rank = 1" in query


def test_error_analysis_reports_accuracy_from_one_pick_not_three_options(mock_conn):
    conn, cur = mock_conn
    conn.__enter__.return_value = conn
    cur.fetchall.return_value = [
        (1, 10, 20, "spf", "3", 0.61, 0.45, 0.08, 0.8, 0.2, None, "3", 2, 0, "elo"),
    ]

    with (
        patch.object(analyze_prediction_errors, "get_db", return_value=conn),
        patch.object(analyze_prediction_errors, "create_error_analyses_batch") as create_batch,
    ):
        result = analyze_prediction_errors.run()

    assert result["analyzed"] == 1
    assert result["correct"] == 1
    assert result["errors_found"] == 0
    assert result["accuracy"] == 1.0
    create_batch.assert_not_called()
