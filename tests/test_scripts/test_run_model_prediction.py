"""Safety gates for the model prediction job."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from scripts.jobs.run_model_prediction import _predict_match_play_type, _run_impl


def _run_with_odds(odds_rows):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = odds_rows

    with (
        patch("scripts.jobs.run_model_prediction._latest_feature_snapshot_id", return_value=7),
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
