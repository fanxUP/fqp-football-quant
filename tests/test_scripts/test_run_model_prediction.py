"""Safety gates for the model prediction job."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from scripts.feature_adjustment import GoalRateAdjustment
from scripts.jobs.run_model_prediction import (
    _load_adaboost_shadow_probabilities,
    _load_bayesian_form_probabilities,
    _load_extra_trees_shadow_probabilities,
    _load_hist_gradient_boosting_shadow_probabilities,
    _load_knn_shadow_probabilities,
    _load_lda_shadow_probabilities,
    _load_logistic_shadow_probabilities,
    _load_mlp_shadow_probabilities,
    _load_trained_bivariate_shared_component,
    _load_trained_elo_probabilities,
    _load_trained_glicko2_probabilities,
    _load_trained_goal_rates,
    _load_trained_negative_binomial_dispersion,
    _load_xgboost_shadow_probabilities,
    _now,
    _predict_match_play_type,
    _run_impl,
    _safe_fair_odds,
    run,
)
from scripts.prediction_input_fence import PredictionInputFence


@pytest.fixture(autouse=True)
def legacy_input_fence():
    # Existing unit fixtures do not model PostgreSQL's input head/isolation.
    with patch(
        "scripts.jobs.run_model_prediction.capture_prediction_input_fence",
        return_value=PredictionInputFence(101, None),
    ) as capture:
        yield capture


def test_xgboost_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_xgboost_shadow_probabilities(
            {"xgboost_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_fair_odds_omits_values_outside_database_precision() -> None:
    """A near-zero probability must not abort the whole scheduled batch."""
    assert _safe_fair_odds(0.5) == 2.0
    assert _safe_fair_odds(0.000001) is None
    assert _safe_fair_odds(0.0000009) is None


def test_logistic_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_logistic_shadow_probabilities(
            {"logistic_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_extra_trees_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_extra_trees_shadow_probabilities(
            {"extra_trees_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_hist_gradient_boosting_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_hist_gradient_boosting_shadow_probabilities(
            {"hist_gradient_boosting_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_adaboost_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_adaboost_shadow_probabilities(
            {"adaboost_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_lda_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_lda_shadow_probabilities(
            {"lda_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_knn_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_knn_shadow_probabilities(
            {"knn_shadow": {"rollout_mode": "shadow"}},
            {"data_completeness_score": 0.9},
        )
        is None
    )


def test_mlp_shadow_requires_a_verified_profile_before_predicting() -> None:
    assert (
        _load_mlp_shadow_probabilities(
            {"mlp_shadow": {"rollout_mode": "shadow"}}, {"data_completeness_score": 0.9}
        )
        is None
    )


def test_bayesian_form_requires_both_teams_to_have_settled_history() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(1, "3")] * 6 + [(2, "0")] * 5

    assert (
        _load_bayesian_form_probabilities(conn, 101, {"home_team_id": 10, "away_team_id": 20})
        is None
    )
    query = cursor.execute.call_args.args[0]
    assert "m.kickoff_time < current_match.kickoff_time" in query
    assert "r.result_status IN ('final', 'confirmed')" in query


def test_xgboost_shadow_prediction_never_enters_committee_votes() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [
            (11, "h", 2.1, "2026-08-09T13:00:00"),
            (12, "d", 3.2, "2026-08-09T13:00:00"),
            (13, "a", 3.6, "2026-08-09T13:00:00"),
        ],
        [],
    ]

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "home_team_id": 10, "away_team_id": 20},
        ),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
        patch(
            "scripts.jobs.run_model_prediction._load_xgboost_shadow_probabilities",
            return_value={"3": 0.52, "1": 0.28, "0": 0.20},
        ),
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote") as store_vote,
    ):
        _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"xgboost_shadow": 7},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-08-09T14:00:00",
            model_parameters={"xgboost_shadow": {"rollout_mode": "shadow"}},
        )

    stored = [call.args[1] for call in store_prediction.call_args_list]
    assert len(stored) == 3
    assert all(item["uncertainty_reason"]["xgboost_shadow_based"] is True for item in stored)
    assert all(item["uncertainty_reason"]["model_independent"] is True for item in stored)
    store_vote.assert_not_called()


def test_bivariate_component_requires_converged_history_and_valid_goal_rates() -> None:
    params = {
        "bivariate_poisson": {
            "shared_goal_component": 0.14,
            "n_matches": 300,
            "converged": True,
        }
    }
    goal_rates = type("GoalRates", (), {"home_lambda": 1.4, "away_lambda": 1.0})()

    assert _load_trained_bivariate_shared_component(params, goal_rates) == 0.14
    params["bivariate_poisson"]["converged"] = False
    assert _load_trained_bivariate_shared_component(params, goal_rates) is None


def test_negative_binomial_shadow_requires_converged_history_and_goal_rates() -> None:
    params = {
        "negative_binomial_shadow": {
            "dispersion": 0.7,
            "n_matches": 240,
            "converged": True,
            "rollout_mode": "shadow",
        }
    }

    assert _load_trained_negative_binomial_dispersion(params, object()) == 0.7
    params["negative_binomial_shadow"]["converged"] = False
    assert _load_trained_negative_binomial_dispersion(params, object()) is None


def test_bivariate_shadow_prediction_never_enters_committee_votes() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [
            (11, "h", 2.1, "2026-08-09T13:00:00"),
            (12, "d", 3.2, "2026-08-09T13:00:00"),
            (13, "a", 3.6, "2026-08-09T13:00:00"),
        ],
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
        },
        "bivariate_poisson": {
            "shared_goal_component": 0.12,
            "n_matches": 300,
            "converged": True,
            "rollout_mode": "shadow",
        },
    }

    with (
        patch(
            "scripts.jobs.run_model_prediction._latest_feature_snapshot",
            return_value={"id": 88, "home_team_id": 10, "away_team_id": 20},
        ),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote") as store_vote,
    ):
        _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type="spf",
            active_models={"bivariate_poisson": 6},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-08-09T14:00:00",
            model_parameters=parameters,
        )

    stored = [call.args[1] for call in store_prediction.call_args_list]
    assert len(stored) == 3
    assert all(item["uncertainty_reason"]["bivariate_poisson_based"] is True for item in stored)
    assert all(item["uncertainty_reason"]["model_independent"] is True for item in stored)
    store_vote.assert_not_called()


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


def test_glicko2_requires_sufficient_history_and_low_rating_deviation() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(1650, 80, 0.06, 12), (1500, 90, 0.06, 14)]

    probabilities = _load_trained_glicko2_probabilities(
        conn,
        {"home_team_id": 10, "away_team_id": 20},
    )

    assert probabilities is not None
    assert probabilities["3"] > probabilities["0"]
    assert cursor.execute.call_args.args[1] == (10, 20)


def _run_with_odds(
    odds_rows,
    output_group_counts=None,
    *,
    play_type="spf",
    active_models=None,
):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = odds_rows
    cursor.fetchone.return_value = None  # No eligible feature snapshot in this fixture.

    with (
        patch("scripts.jobs.run_model_prediction.store_model_prediction") as store_prediction,
        patch("scripts.jobs.run_model_prediction.store_committee_vote") as store_vote,
    ):
        result = _predict_match_play_type(
            conn=conn,
            mid=101,
            home_team_name="主队",
            away_team_name="客队",
            play_type=play_type,
            active_models=active_models or {"market_baseline": 1},
            rho=-0.08,
            mle_rho=None,
            predict_time="2026-07-13T14:00:00",
            prediction_run_id="00000000-0000-0000-0000-000000000001"
            if output_group_counts is not None
            else None,
            output_group_counts=output_group_counts,
        )

    return result, store_prediction, store_vote


def test_prediction_skips_match_without_official_odds():
    result, store_prediction, store_vote = _run_with_odds([])

    assert result == (0, 0)
    store_prediction.assert_not_called()
    store_vote.assert_not_called()


def test_prediction_counts_missing_odds_as_skipped_expected_group():
    output_group_counts = {}

    result, _store_prediction, _store_vote = _run_with_odds([], output_group_counts)

    assert result == (0, 0)
    assert output_group_counts["expected"] == 1
    assert output_group_counts["completed"] == 0
    assert output_group_counts["expected_models"] == [("market_baseline", 1)]
    assert output_group_counts["skipped"][0]["reason"] == "official_odds_missing"


def test_missing_rqspf_odds_count_models_that_need_a_handicap():
    output_group_counts = {}

    _run_with_odds(
        [],
        output_group_counts,
        play_type="rqspf",
        active_models={"maher_poisson": 1},
    )

    assert output_group_counts["expected"] == 1
    assert output_group_counts["completed"] == 0
    assert output_group_counts["expected_models"] == [("maher_poisson", 1)]
    assert output_group_counts["skipped"][0]["reason"] == "official_odds_missing"


def test_prediction_skips_incomplete_spf_market_instead_of_inventing_odds():
    result, store_prediction, store_vote = _run_with_odds(
        [(11, "h", 2.1, "2026-08-09T13:00:00"), (12, "d", 3.2, "2026-08-09T13:00:00")]
    )

    assert result == (0, 0)
    store_prediction.assert_not_called()
    store_vote.assert_not_called()


def test_market_validation_failure_is_recorded_as_a_missing_output_group():
    from scripts.market_metric_validation import MarketMetricValidationError

    counts = {}
    with (
        patch(
            "scripts.jobs.run_model_prediction.validate_market",
            side_effect=MarketMetricValidationError("invalid market fixture"),
        ),
        patch("scripts.jobs.run_model_prediction.store_derived_play_predictions", return_value=0),
    ):
        result, _store_prediction, _store_vote = _run_with_odds(
            [
                (11, "h", 2.1, "2026-08-09T13:00:00"),
                (12, "d", 3.2, "2026-08-09T13:00:00"),
                (13, "a", 3.6, "2026-08-09T13:00:00"),
            ],
            counts,
        )

    assert result == (0, 0)
    assert counts["expected"] == 1
    assert counts["completed"] == 0
    assert counts["skipped"] == [
        {
            "match_id": 101,
            "model_version_id": 1,
            "model_name": "market_baseline",
            "play_type": "spf",
            "reason": "market_validation_failed",
        }
    ]


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
        "completion_reason": "no_open_markets",
        "output_groups_expected": 0,
        "output_groups_completed": 0,
        "output_groups_skipped": 0,
        "output_group_skips": [],
    }
    predict.assert_not_called()


def test_run_impl_aggregates_missing_prediction_group_counts():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(1, "market_baseline", {})],
        [(101, "主队", "客队")],
        [(101, "spf")],
    ]
    cursor.fetchone.return_value = None
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    def skip_groups(*_args, output_group_counts, **_kwargs):
        output_group_counts.update(
            expected=2,
            completed=0,
            skipped=[
                {
                    "match_id": 101,
                    "model_version_id": 1,
                    "model_name": "market_baseline",
                    "play_type": "spf",
                    "reason": "official_odds_incomplete",
                },
                {
                    "match_id": 101,
                    "model_version_id": 2,
                    "model_name": "maher_poisson",
                    "play_type": "spf",
                    "reason": "official_odds_incomplete",
                },
            ],
        )
        return 0, 0

    with (
        patch("scripts.jobs.run_model_prediction.get_db", return_value=db_context),
        patch(
            "scripts.jobs.run_model_prediction._predict_match_play_type",
            side_effect=skip_groups,
        ),
    ):
        result = _run_impl()

    assert result["output_groups_expected"] == 2
    assert result["output_groups_completed"] == 0
    assert result["output_groups_skipped"] == 2
    assert result["completion_reason"] == "expected_output_groups_missing"
    assert [item["reason"] for item in result["output_group_skips"]] == [
        "official_odds_incomplete",
        "official_odds_incomplete",
    ]


def test_prediction_without_odds_records_each_expected_group_as_skipped():
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = []
    counts = {}

    with patch("scripts.jobs.run_model_prediction._latest_feature_snapshot", return_value=None):
        assert _predict_match_play_type(
            conn,
            101,
            "主队",
            "客队",
            "spf",
            {"market_baseline": 7},
            -0.08,
            None,
            "2026-10-23T10:00:00",
            prediction_run_id="test-run",
            output_group_counts=counts,
        ) == (0, 0)

    assert counts["expected"] == 1
    assert counts["completed"] == 0
    assert counts["skipped"] == [
        {
            "match_id": 101,
            "model_version_id": 7,
            "model_name": "market_baseline",
            "play_type": "spf",
            "reason": "official_odds_missing",
        }
    ]


def test_match_specific_prediction_still_requires_a_sellable_future_match():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[(1, "market_baseline")], []]
    cursor.fetchone.return_value = None
    db_context = MagicMock()
    db_context.__enter__.return_value = conn

    with patch("scripts.jobs.run_model_prediction.get_db", return_value=db_context):
        result = _run_impl(match_id=101)

    assert result == {
        "status": "ok",
        "predictions": 0,
        "note": "no matches to predict",
        "completion_reason": "no_matches",
        "output_groups_expected": 0,
        "output_groups_completed": 0,
        "output_groups_skipped": 0,
        "output_group_skips": [],
    }
    queries = [" ".join(call.args[0].split()) for call in cursor.execute.call_args_list]
    match_query = next(q for q in queries if "FROM official_matches WHERE id = %s" in q)
    assert "sale_status = 'selling'" in match_query
    assert "kickoff_time > timezone('Asia/Shanghai', NOW())" in match_query
    assert "sale_stop_time" in match_query


def test_poisson_prediction_persists_raw_and_feature_adjusted_probabilities():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [
            (11, "h", 2.1, "2026-07-16T13:00:00"),
            (12, "d", 3.2, "2026-07-16T13:00:00"),
            (13, "a", 3.6, "2026-07-16T13:00:00"),
        ],
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
    assert all(item["input_fence"] == PredictionInputFence(101, None) for item in stored)
    assert all(item["uncertainty_reason"]["feature_adjustment"]["applied"] for item in stored)


def test_converged_historical_maher_model_is_persisted_as_independent() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [
            (11, "h", 2.1, "2026-07-16T13:00:00"),
            (12, "d", 3.2, "2026-07-16T13:00:00"),
            (13, "a", 3.6, "2026-07-16T13:00:00"),
        ],
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
        [
            (11, "h", 2.1, "2026-07-16T13:00:00"),
            (12, "d", 3.2, "2026-07-16T13:00:00"),
            (13, "a", 3.6, "2026-07-16T13:00:00"),
        ],
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
            predict_time="2026-07-16T14:00:00",
        )

    assert result == (21, 0)
    store_vote.assert_not_called()


def test_each_prediction_binds_its_matching_official_option_snapshot():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [
            (11, "h", 2.1, "2026-07-16T13:00:00"),
            (12, "d", 3.2, "2026-07-16T13:00:00"),
            (13, "a", 3.6, "2026-07-16T13:00:00"),
        ],
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
        patch("scripts.jobs.run_model_prediction.get_db"),
        patch(
            "scripts.jobs.run_model_prediction.fingerprint_runtime_sources",
            return_value={"files": {}, "sha256": "a" * 64},
        ),
        patch("scripts.jobs.run_model_prediction.create_prediction_run"),
        patch("scripts.jobs.run_model_prediction.finalize_prediction_run"),
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


def test_prediction_job_records_run_identity_and_preserves_partial_status() -> None:
    with (
        patch("scripts.jobs.run_model_prediction.start_tracked_job", return_value=9),
        patch("scripts.jobs.run_model_prediction.finish_tracked_job"),
        patch("scripts.jobs.run_model_prediction.get_db"),
        patch(
            "scripts.jobs.run_model_prediction.fingerprint_runtime_sources",
            return_value={"files": {}, "sha256": "a" * 64},
        ),
        patch("scripts.jobs.run_model_prediction.create_prediction_run") as create_run,
        patch("scripts.jobs.run_model_prediction.finalize_prediction_run") as finalize_run,
        patch(
            "scripts.jobs.run_model_prediction._run_impl",
            return_value={
                "status": "ok",
                "predictions": 3,
                "input_updates_skipped": 1,
                "output_groups_expected": 3,
                "output_groups_completed": 1,
                "output_groups_skipped": 2,
                "output_group_skips": [
                    {
                        "match_id": 101,
                        "model_version_id": 8,
                        "model_name": "maher_poisson",
                        "play_type": "spf",
                        "reason": "official_odds_incomplete",
                    },
                    {
                        "match_id": 102,
                        "model_version_id": 8,
                        "model_name": "maher_poisson",
                        "play_type": "spf",
                        "reason": "input_update_superseded",
                    },
                ],
                "completion_reason": "expected_output_groups_missing",
            },
        ) as run_impl,
    ):
        result = run()

    prediction_run_id = create_run.call_args.kwargs["run_id"]
    assert create_run.call_args.kwargs["ai_job_run_id"] == 9
    assert run_impl.call_args.kwargs["prediction_run_id"] == prediction_run_id
    assert finalize_run.call_args.kwargs["run_status"] == "partial"
    assert finalize_run.call_args.kwargs["output_summary"] == {
        "expected_groups": 3,
        "completed_groups": 1,
        "skipped_groups": 2,
        "missing_groups": [
            {
                "match_id": 101,
                "model_version_id": 8,
                "model_name": "maher_poisson",
                "play_type": "spf",
                "reason": "official_odds_incomplete",
            },
            {
                "match_id": 102,
                "model_version_id": 8,
                "model_name": "maher_poisson",
                "play_type": "spf",
                "reason": "input_update_superseded",
            },
        ],
        "input_updates_skipped": 1,
        "completion_reason": "expected_output_groups_missing",
    }
    assert result["input_updates_skipped"] == 1


def test_prediction_job_marks_missing_output_groups_partial() -> None:
    with (
        patch("scripts.jobs.run_model_prediction.start_tracked_job", return_value=9),
        patch("scripts.jobs.run_model_prediction.finish_tracked_job"),
        patch("scripts.jobs.run_model_prediction.get_db"),
        patch(
            "scripts.jobs.run_model_prediction.fingerprint_runtime_sources",
            return_value={"files": {}, "sha256": "a" * 64},
        ),
        patch("scripts.jobs.run_model_prediction.create_prediction_run"),
        patch("scripts.jobs.run_model_prediction.finalize_prediction_run") as finalize_run,
        patch(
            "scripts.jobs.run_model_prediction._run_impl",
            return_value={
                "status": "ok",
                "predictions": 0,
                "output_groups_expected": 1,
                "output_groups_completed": 0,
                "output_groups_skipped": 1,
                "output_group_skips": [
                    {
                        "match_id": 101,
                        "model_version_id": 8,
                        "model_name": "maher_poisson",
                        "play_type": "spf",
                        "reason": "official_odds_missing",
                    }
                ],
                "completion_reason": "expected_output_groups_missing",
            },
        ),
    ):
        run()

    assert finalize_run.call_args.kwargs["run_status"] == "partial"


def test_prediction_job_persists_no_input_completion_reason() -> None:
    with (
        patch("scripts.jobs.run_model_prediction.start_tracked_job", return_value=9),
        patch("scripts.jobs.run_model_prediction.finish_tracked_job"),
        patch("scripts.jobs.run_model_prediction.get_db"),
        patch(
            "scripts.jobs.run_model_prediction.fingerprint_runtime_sources",
            return_value={"files": {}, "sha256": "a" * 64},
        ),
        patch("scripts.jobs.run_model_prediction.create_prediction_run"),
        patch("scripts.jobs.run_model_prediction.finalize_prediction_run") as finalize_run,
        patch(
            "scripts.jobs.run_model_prediction._run_impl",
            return_value={
                "status": "ok",
                "predictions": 0,
                "completion_reason": "no_open_markets",
                "output_groups_expected": 0,
                "output_groups_completed": 0,
                "output_groups_skipped": 0,
                "output_group_skips": [],
            },
        ),
    ):
        run()

    assert finalize_run.call_args.kwargs["run_status"] == "completed"
    assert finalize_run.call_args.kwargs["output_summary"] == {
        "expected_groups": 0,
        "completed_groups": 0,
        "skipped_groups": 0,
        "missing_groups": [],
        "input_updates_skipped": 0,
        "completion_reason": "no_open_markets",
    }


def test_input_fence_is_captured_before_feature_or_odds_reads(legacy_input_fence):
    events = []
    legacy_input_fence.side_effect = lambda *args: (
        events.append("capture") or PredictionInputFence(101, 7)
    )
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchall.side_effect = lambda: (
        events.append("odds") or []
    )
    with patch(
        "scripts.jobs.run_model_prediction._latest_feature_snapshot",
        side_effect=lambda *a, **k: events.append("features") or None,
    ):
        _predict_match_play_type(
            conn,
            101,
            "home",
            "away",
            "spf",
            {"market_baseline": 1},
            -0.08,
            None,
            "2026-10-20T12:00:00",
        )
    assert events == ["capture", "features", "odds"]


def test_superseded_match_does_not_abort_other_match_predictions():
    from scripts.prediction_input_updates import InputUpdateSuperseded

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(1, "market_baseline")],
        [(101, "a", "b"), (102, "c", "d")],
        [(101, "spf"), (102, "spf")],
    ]
    cursor.fetchone.return_value = None
    with (
        patch("scripts.jobs.run_model_prediction.get_db") as db,
        patch(
            "scripts.jobs.run_model_prediction._predict_match_play_type",
            side_effect=[InputUpdateSuperseded("changed"), (3, 0)],
        ) as predict,
    ):
        db.return_value.__enter__.return_value = conn
        result = _run_impl()
    assert result["predictions"] == 3 and predict.call_count == 2
    conn.rollback.assert_called_once()


def test_input_lock_contention_does_not_abort_other_match_predictions():
    from psycopg2.errors import LockNotAvailable

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [(1, "market_baseline")],
        [(101, "a", "b"), (102, "c", "d")],
        [(101, "spf"), (102, "spf")],
    ]
    cursor.fetchone.return_value = None
    with (
        patch("scripts.jobs.run_model_prediction.get_db") as db,
        patch(
            "scripts.jobs.run_model_prediction._predict_match_play_type",
            side_effect=[LockNotAvailable("locked"), (3, 0)],
        ) as predict,
    ):
        db.return_value.__enter__.return_value = conn
        result = _run_impl()
    assert result["predictions"] == 3 and predict.call_count == 2
    conn.rollback.assert_called_once()
