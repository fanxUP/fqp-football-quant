"""Safety gates for the model prediction job."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from scripts.feature_adjustment import GoalRateAdjustment
from scripts.jobs.run_model_prediction import _now, _predict_match_play_type, _run_impl, run


def test_prediction_timestamp_uses_naive_business_wall_clock() -> None:
    shanghai_now = datetime(2026, 7, 15, 17, 30, tzinfo=ZoneInfo("Asia/Shanghai"))

    with patch("scripts.jobs.run_model_prediction.business_now", return_value=shanghai_now):
        assert _now() == "2026-07-15T17:30:00"


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
