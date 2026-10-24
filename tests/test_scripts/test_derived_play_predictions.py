from unittest.mock import MagicMock, patch

import pytest

from scripts.derived_play_predictions import store_derived_play_predictions
from scripts.poisson_model import score_matrix
from scripts.prediction_input_fence import PredictionInputFence


@pytest.mark.parametrize(
    ("play_type", "common_option", "rare_option"),
    [("bf", "0:0", "0:5"), ("zjq", "0", "7")],
)
def test_rare_derived_outcomes_keep_history_without_overflowing_fair_odds(
    play_type, common_option, rare_option
):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (101, play_type, common_option, 1.5, "2026-10-24T12:14:00"),
        (102, play_type, rare_option, 1.8, "2026-10-24T12:14:00"),
    ]
    matrix = score_matrix(0.05, 0.05)
    with patch("scripts.derived_play_predictions.store_model_prediction") as store:
        count = store_derived_play_predictions(
            conn=conn,
            match_id=9,
            active_models={"market_baseline": 1, "maher_poisson": 2, "dixon_coles": 3},
            raw_poisson_matrix=matrix,
            poisson_matrix=matrix,
            raw_dc_matrix=matrix,
            dc_matrix=matrix,
            raw_lambdas=(0.05, 0.05),
            adjusted_lambdas=(0.05, 0.05),
            feature_snapshot_id=88,
            predict_time="2026-10-24T12:15:00",
        )
    rows = [call.args[1] for call in store.call_args_list]
    assert count == 6
    assert len(rows) == 6
    rare = [r for r in rows if r["option_code"] == rare_option and r["model_version_id"] != 1]
    assert len(rare) == 2
    for row in rare:
        assert row["fair_odds"] is None
        assert row["model_probability"] == 0.0
        assert row["ev"] == -1.0
        assert row["validation_status"] == "valid"
        assert row["odds_snapshot_id"] == 102
    assert all(r["fair_odds"] > 0 for r in rows if r not in rare)


def test_derived_history_stores_every_official_option_for_each_capable_model():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (101, "zjq", "0", 1.5, "2026-07-16T13:00:00"),
        (102, "zjq", "7", 1.8, "2026-07-16T13:00:00"),
        (201, "bf", "1:0", 1.5, "2026-07-16T13:00:00"),
        (202, "bf", "other_h", 1.8, "2026-07-16T13:00:00"),
        (301, "bqc", "33", 1.5, "2026-07-16T13:00:00"),
        (302, "bqc", "10", 1.8, "2026-07-16T13:00:00"),
    ]
    raw_poisson = score_matrix(1.3, 1.1)
    adjusted_poisson = score_matrix(1.6, 0.9)
    raw_dc = score_matrix(1.25, 1.05)
    adjusted_dc = score_matrix(1.5, 0.95)
    token = PredictionInputFence(9, 12)

    with patch("scripts.derived_play_predictions.store_model_prediction") as store:
        count = store_derived_play_predictions(
            input_fence=token,
            conn=conn,
            match_id=9,
            active_models={
                "market_baseline": 1,
                "maher_poisson": 2,
                "dixon_coles": 3,
                "elo_rating": 4,
            },
            raw_poisson_matrix=raw_poisson,
            poisson_matrix=adjusted_poisson,
            raw_dc_matrix=raw_dc,
            dc_matrix=adjusted_dc,
            raw_lambdas=(1.3, 1.1),
            adjusted_lambdas=(1.6, 0.9),
            feature_snapshot_id=88,
            predict_time="2026-07-16T14:00:00",
            model_independence={"maher_poisson": True, "dixon_coles": True},
        )

    stored = [call.args[1] for call in store.call_args_list]
    assert count == 14
    assert all(row["input_fence"] is token for row in stored)
    assert {(row["play_type"], row["option_code"]) for row in stored} == {
        ("zjq", "0"),
        ("zjq", "7"),
        ("bf", "1:0"),
        ("bf", "other_h"),
        ("bqc", "33"),
        ("bqc", "10"),
    }
    assert {row["model_version_id"] for row in stored} == {1, 2, 3}
    assert all(row["odds_snapshot_id"] is not None for row in stored)
    assert all(row["feature_snapshot_id"] == 88 for row in stored)
    assert all(row["uncertainty_reason"]["recommendation_filtered"] is False for row in stored)
    assert all(
        row["uncertainty_reason"]["model_independent"] is True
        for row in stored
        if row["model_version_id"] in {2, 3}
    )
    zjq_seven = [row for row in stored if row["play_type"] == "zjq" and row["option_code"] == "7"]
    assert all(row["model_probability"] > 0 for row in zjq_seven)
    assert any(row["ev"] < 0 for row in stored)
    assert any(
        row["raw_model_probability"] != row["model_probability"]
        for row in stored
        if row["model_version_id"] in {2, 3}
    )


def test_derived_history_does_nothing_without_official_odds():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = []
    matrix = score_matrix(1.3, 1.1)

    with patch("scripts.derived_play_predictions.store_model_prediction") as store:
        count = store_derived_play_predictions(
            conn=conn,
            match_id=9,
            active_models={"maher_poisson": 2},
            raw_poisson_matrix=matrix,
            poisson_matrix=matrix,
            raw_dc_matrix=matrix,
            dc_matrix=matrix,
            raw_lambdas=(1.3, 1.1),
            adjusted_lambdas=(1.3, 1.1),
            feature_snapshot_id=88,
            predict_time="2026-07-16T14:00:00",
        )

    assert count == 0
    store.assert_not_called()


def test_half_full_time_has_only_market_baseline_until_joint_model_is_validated():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (301, "bqc", "33", 1.5, "2026-10-17T09:00:00"),
        (302, "bqc", "10", 1.8, "2026-10-17T09:00:00"),
    ]
    matrix = score_matrix(1.7, 0.9)
    with patch("scripts.derived_play_predictions.store_model_prediction") as store:
        count = store_derived_play_predictions(
            conn=conn,
            match_id=9,
            active_models={"market_baseline": 1, "maher_poisson": 2, "dixon_coles": 3},
            raw_poisson_matrix=matrix,
            poisson_matrix=matrix,
            raw_dc_matrix=matrix,
            dc_matrix=matrix,
            raw_lambdas=(1.7, 0.9),
            adjusted_lambdas=(1.7, 0.9),
            feature_snapshot_id=88,
            predict_time="2026-10-17T10:00:00",
            model_independence={"maher_poisson": True, "dixon_coles": True},
        )
    rows = [call.args[1] for call in store.call_args_list]
    assert count == 2
    assert {row["model_version_id"] for row in rows} == {1}
    assert all(row["model_probability"] == row["market_probability"] for row in rows)
    assert all(row["confidence_score"] is None for row in rows)
    assert all(not row["uncertainty_reason"]["model_independent"] for row in rows)


def test_same_goal_family_and_market_baseline_cannot_manufacture_derived_confidence():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        (101, "zjq", "0", 1.5, "2026-10-17T09:00:00"),
        (102, "zjq", "7", 1.8, "2026-10-17T09:00:00"),
    ]
    matrix = score_matrix(1.7, 0.9)
    with patch("scripts.derived_play_predictions.store_model_prediction") as store:
        count = store_derived_play_predictions(
            conn=conn,
            match_id=9,
            active_models={"market_baseline": 1, "maher_poisson": 2, "dixon_coles": 3},
            raw_poisson_matrix=matrix,
            poisson_matrix=matrix,
            raw_dc_matrix=matrix,
            dc_matrix=matrix,
            raw_lambdas=(1.7, 0.9),
            adjusted_lambdas=(1.7, 0.9),
            feature_snapshot_id=88,
            predict_time="2026-10-17T10:00:00",
            model_independence={"maher_poisson": True, "dixon_coles": True},
        )
    assert count == 6
    for call in store.call_args_list:
        row = call.args[1]
        for key in (
            "confidence_score",
            "risk_score",
            "probability_lower_bound",
            "probability_upper_bound",
            "uncertainty_score",
        ):
            assert row[key] is None
        assert row["uncertainty_reason"]["confidence_status"] == "uncalibrated"
