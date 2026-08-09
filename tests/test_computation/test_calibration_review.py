from scripts.calibration_review import review_calibration_profile, review_calibration_trend


def test_marks_profile_ready_for_manual_review_only_after_conservative_gate():
    review = review_calibration_profile(
        {"sample_count": 320, "log_loss_before": 1.04, "log_loss_after": 1.02}
    )

    assert review == {
        "status": "ready_for_manual_review",
        "label": "可人工评审",
        "sampleThreshold": 300,
        "improvementThreshold": 0.005,
        "logLossImprovement": 0.02,
        "affectsDecisionPath": False,
    }


def test_keeps_insufficient_or_non_improving_profile_in_observation():
    review = review_calibration_profile(
        {"sample_count": 299, "log_loss_before": 1.02, "log_loss_after": 1.02}
    )

    assert review["status"] == "observing"
    assert review["label"] == "持续观察"
    assert review["affectsDecisionPath"] is False


def test_marks_latest_profile_trend_as_improving_without_changing_decision_path():
    trend = review_calibration_trend(
        [
            {"created_at": "2026-08-01T23:42:00", "log_loss_after": 1.04},
            {"created_at": "2026-08-08T23:42:00", "log_loss_after": 1.02},
        ]
    )

    assert trend == {
        "status": "improving",
        "label": "近期改善",
        "latestLogLoss": 1.02,
        "previousLogLoss": 1.04,
        "logLossChange": -0.02,
        "profileCount": 2,
        "affectsDecisionPath": False,
    }


def test_marks_single_profile_trend_as_insufficient_history():
    trend = review_calibration_trend(
        [{"created_at": "2026-08-08T23:42:00", "log_loss_after": 1.02}]
    )

    assert trend["status"] == "insufficient_history"
    assert trend["label"] == "历史不足"
    assert trend["affectsDecisionPath"] is False
