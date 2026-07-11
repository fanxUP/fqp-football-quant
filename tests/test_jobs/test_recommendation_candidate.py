from datetime import datetime

from scripts.jobs.run_recommendation_candidate import _prediction_sp_value


def test_prediction_sp_value_does_not_treat_kickoff_as_sp():
    row = tuple(range(15)) + (datetime(2026, 7, 11, 3), 1.46, "market_baseline")

    assert _prediction_sp_value(row) == 1.46

