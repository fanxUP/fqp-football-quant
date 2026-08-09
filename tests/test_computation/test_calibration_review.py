from scripts.calibration_review import review_calibration_profile


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
