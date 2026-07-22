"""Safety gates for the model prediction job."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scripts.feature_adjustment import GoalRateAdjustment
from scripts.jobs.run_model_prediction import (
    _load_trained_elo_probabilities,
    _load_trained_goal_rates,
    _now,
    _predict_match_play_type,
    _run_impl,
    run,
)


def test_trained_maher_parameters_produce_independent_team_goal_rates() -> None:
    parameters = {
        "maher_poisson": {
            "attack": {"10": 0.35, "20": -0.15},
            "defense": {"10": -0.10, "20": 0.20},
            "team_match_counts": {"10": 12, "20": 9},
            "home_advantage": 0.25,
            "league_intercept": 0.10,
            "n_matches": 100,
            "converged": True,
        }
    }

    result = _load_trained_goal_rates(
        parameters,
        {"home_team_id": 10, "away_team_id": 20},
    )

    assert result is not None
    assert result.home_lambda > result.away_lambda
    assert result.minimum_team_matches == 9


def test_non_converged_maher_parameters_are_not_actionable() -> None:
    parameters = {
        "maher_poisson": {
            "attack": {"10": 0.35, "20": -0.15},
            "defense": {"10": -0.10, "20": 0.20},
            "team_match_counts": {"10": 12, "20": 9},
            "home_advantage": 0.25,
            "league_intercept": 0.10,
            "n_matches": 100,
            "converged": False,
        }
    }

    assert (
        _load_trained_goal_rates(
            parameters,
            {"home_team_id": 10, "away_team_id": 20},
        )
        is None
    )


def test_prediction_timestamp_uses_naive_business_wall_clock() -> None:
    shanghai_now = datetime(2026, 7, 15, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    with patch("scripts.jobs.run_model_prediction.business_now", return_value=shanghai_now):
        assert _now() == "2026-07-15T17:30:00"


def test_elo_cold_start_is_not_treated_as_an_independent_model_signal() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(1300, 0), (1300, 0)]

    probabilities = _load_trained_elo_probabilities(
        conn,
        {"home_team_id": 10, "away_team_id": 20},
    )

    assert probabilities is None


def test_trained_elo_uses_snapshot_home_and_away_team_order() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(1450, 20), (1620, 30)]

    probabilities = _load_trained_elo_probabilities(
        conn,
        {"home_team_id": 10, "away_team_id": 20},
    )

    assert probabilities is not None
    assert probabilities["0"] > probabilities["3"]
    assert cursor.execute.call_args.args[1] == (10, 20)


def _run_with_odds(odds_rows):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = odds_rows

    with (
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote") as store_vote,
    ):
        result = _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"market_baseline": 1},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-07-13T14:00:00",
        )

    return result, store_prediction, store_vote


def test_prediction_skips_match_without_official_odds():
    result, store_prediction, store_vote = _run_with_odds([])

    assert result == (0, 0)
    store_prediction.assert_not_called()
    store_vote.assert_not_called()


def test_prediction_skips_incomplete_spf_market_instead_of_inventing_odds():
    result, store_prediction, store_vote = _run_with_odds(
        [(11, "h", 2.1), (12, "d", 3.2)]
    )

    assert result == (0, 0)
    store_prediction.assert_not_called()
    store_vote.assert_not_called()


def test_prediction_job_does_not_fallback_to_spf_when_no_market_is_open():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(1, "market_baseline")],
        [(101, "主队", "客队")],
        [],
    ]
    cursor.fetchone.return_value = None

    db_context = MagicMock()
    db_context.__enter__.return_value = conn
    with (
        patch("scripts.jobs.run_model_prediction.get_db", return_value=db_context),
        patch("scripts.jobs.run_model_prediction._predict_match_play_type") as predict,
    ):
        result = _run_impl()

    assert result == {
        "status": "ok",
        "predictions": 0,
        "votes": 0,
        "matches_processed": 0,
        "note": "no matches with open official markets",
    }
    predict.assert_not_called()


def test_match_specific_prediction_still_requires_a_sellable_future_match():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[(1, "market_baseline")], []]
    cursor.fetchone.return_value = None
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    with patch("scripts.jobs.run_model_prediction.get_db", return_value=db_context):
        result = _run_impl(match_id=101)

    assert result == {"status": "ok", "predictions": 0, "note": "no matches to predict"}
    queries = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
    match_query = next(q for q in queries if "FROM official_matches WHERE id = %s" in q)
    assert "sale_status = 'selling'" in match_query
    assert "kickoff_time > timezone('Asia/Shanghai', NOW())" in match_query
    assert "sale_stop_time" in match_query


def test_poisson_prediction_persists_raw_and_feature_adjusted_probabilities():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(11, "h", 2.1), (12, "d", 3.2), (13, "a", 3.6)],
        [],
    ]
    adjustment = GoalRateAdjustment(
        home_lambda=2.0,
        away_lambda=0.5,
        applied=True,
        home_log_shift=0.12,
        total_goal_multiplier=1.0,
        reasons=[{"feature": "motivation_diff", "value": 20.0, "log_shift": 0.016}],
    )

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "data_completeness_score": 70},
        ),
        patch("scripts.jobs.run_model_prediction.adjust_goal_rates", return_value=adjustment),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote"),
    ):
        _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"maher_poisson": 1},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-07-13T14:00:00",
        )

    stored = [call.args[1] for call in store_prediction.call_args_list]
    assert len(stored) == 3
    assert any(item["raw_model_probability"] != item["model_probability"] for item in stored)
    assert all(item["feature_snapshot_id"] == 88 for item in stored)
    assert all(item["uncertainty_reason"]["feature_adjustment"]["applied"] for item in stored)


def test_converged_historical_maher_model_is_persisted_as_independent() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(11, "h", 2.1), (12, "d", 3.2), (13, "a", 3.6)],
        [],
    ]
    parameters = {
        "maher_poisson": {
            "attack": {"10": 0.35, "20": -0.15},
            "defense": {"10": -0.10, "20": 0.20},
            "team_match_counts": {"10": 12, "20": 9},
            "home_advantage": 0.25,
            "league_intercept": 0.10,
            "n_matches": 100,
            "converged": True,
        }
    }

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "home_team_id": 10, "away_team_id": 20},
        ),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote"),
    ):
        _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"maher_poisson": 1},
            rho=-0.05,
            mle_rho=-0.05,
            predict_time="2026-07-16T14:00:00",
            model_parameters=parameters,
        )

    stored = [call.args[1] for call in store_prediction.call_args_list]
    assert len(stored) == 3
    assert all(item["uncertainty_reason"]["model_independent"] is True for item in stored)
    assert all(item["uncertainty_reason"]["goal_rate_source"] == "trained_maher" for item in stored)
    assert any(item["model_probability"] != item["market_probability"] for item in stored)


def test_spf_prediction_includes_complete_derived_history_in_count():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(11, "h", 2.1), (12, "d", 3.2), (13, "a", 3.6)],
        [],
    ]

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "data_completeness_score": 70},
        ),
        patch(
            "scripts.jobs.run_model_prediction.store_derived_play_predictions",
            return_value=18,
        ),
        patch("scripts.jobs.run_model_prediction.store_model_prediction"),
        patch("scripts.jobs.run_model_prediction.store_committee_vote"),
    ):
        result = _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"market_baseline": 1},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-07-16T14:00:00",
        )

    assert result == (21, 3)


def test_each_prediction_binds_its_matching_official_option_snapshot():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(11, "h", 2.1), (12, "d", 3.2), (13, "a", 3.6)],
        [],
    ]

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "data_completeness_score": 70},
        ),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote"),
    ):
        _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"market_baseline": 1},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-07-16T14:00:00",
        )

    stored = {call.args[1]["option_code"]: call.args[1] for call in store_prediction.call_args_list}
    assert stored["3"]["odds_snapshot_id"] == 11
    assert stored["1"]["odds_snapshot_id"] == 12
    assert stored["0"]["odds_snapshot_id"] == 13


def test_prediction_job_requires_odds_and_feature_snapshot_jobs() -> None:
    with (
        patch("scripts.jobs.run_model_prediction.start_tracked_job", return_value=9) as start,
        patch("scripts.jobs.run_model_prediction.finish_tracked_job"),
        patch(
            "scripts.jobs.run_model_prediction._run_impl",
            return_value={"status": "ok", "predictions": 0},
        ),
    ):
        run()

    assert start.call_args.kwargs["dependencies"] == [
        "official_odds_snapshot",
        "feature_snapshot_build",
    ]
