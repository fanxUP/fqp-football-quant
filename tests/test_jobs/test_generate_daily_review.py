from unittest.mock import patch

from scripts.jobs import generate_daily_review


def test_settlement_roi_uses_total_profit_over_total_stake():
    totals = generate_daily_review._settlement_totals(
        [
            ("real", 100, 120, 20, 0.9),
            ("simulation", 40, 30, -10, -0.1),
        ]
    )

    assert totals["real"]["roi"] == 0.2
    assert totals["simulation"]["roi"] == -0.25


def test_daily_review_only_counts_prematch_features_and_predictions(mock_conn):
    conn, cur = mock_conn
    conn.__enter__.return_value = conn
    cur.fetchone.side_effect = [(3,), (2,), (2,), (0,), (0,), (0,), (0,), (0,)]
    cur.fetchall.side_effect = [[], []]

    with (
        patch.object(generate_daily_review, "get_db", return_value=conn),
        patch.object(generate_daily_review, "daily_summary", return_value="summary"),
        patch.object(generate_daily_review, "upsert_daily_review", return_value=7),
        patch.object(generate_daily_review, "generate_report", return_value={}),
    ):
        generate_daily_review._run_impl(review_date="2026-07-14")

    queries = [" ".join(call.args[0].split()) for call in cur.execute.call_args_list]
    feature_query = next(q for q in queries if "FROM match_feature_snapshots fs" in q)
    prediction_query = next(q for q in queries if "FROM model_predictions mp" in q)
    ticket_queries = [q for q in queries if "FROM simulation_tickets" in q]
    error_query = next(q for q in queries if "FROM prediction_error_analysis" in q)

    assert "fs.snapshot_time < m.kickoff_time" in feature_query
    assert "mp.predict_time < m.kickoff_time" in prediction_query
    assert "mp.validation_status = 'valid'" in prediction_query
    assert ticket_queries
    assert all(
        "ticket_status IN ('generated', 'activated', 'settled')" in query
        for query in ticket_queries
    )
    assert "JOIN official_matches m ON m.id =" in error_query
    assert "m.business_date = %s" in error_query
