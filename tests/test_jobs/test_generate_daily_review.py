from unittest.mock import patch

from scripts.jobs import generate_daily_review


def test_daily_review_only_counts_prematch_features_and_predictions(mock_conn):
    conn, cur = mock_conn
    conn.__enter__.return_value = conn
    cur.fetchone.side_effect = [(3,), (2,), (2,), (0,), (0,), (0,), (0,), (0,)]
    cur.fetchall.side_effect = [[], []]

    with (
        patch.object(generate_daily_review, "get_db", return_value=conn),
        patch.object(generate_daily_review, "daily_summary", return_value="summary"),
        patch.object(generate_daily_review, "upsert_daily_review", return_value=7),
    ):
        generate_daily_review._run_impl(review_date="2026-07-14")

    queries = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    feature_query = next(q for q in queries if "FROM match_feature_snapshots fs" in q)
    prediction_query = next(q for q in queries if "FROM model_predictions mp" in q)
    error_query = next(q for q in queries if "FROM prediction_error_analysis" in q)

    assert "fs.snapshot_time < m.kickoff_time" in feature_query
    assert "mp.predict_time < m.kickoff_time" in prediction_query
    assert "JOIN official_matches m ON m.id =" in error_query
    assert "m.business_date = %s" in error_query
