from scripts.calibration_review import review_calibration_profile, review_calibration_trend


def test_marks_profile_ready_for_manual_review_only_after_conservative_gate():
    review = review_calibration_profile(
        {"sample_count": 320, "log_loss_before": 1.04, "log_loss_after": 1.02}
    )

    assert review == {
        "status": "ready_for_manual_review",
        "label": "具备人工评审基础",
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
            {"created_at": "2026-08-01T23:42:00", "log_loss_after": 1.04, "sample_count": 300},
            {"created_at": "2026-08-08T23:42:00", "log_loss_after": 1.02, "sample_count": 320},
        ]
    )

    assert trend == {
        "status": "improving",
        "label": "近期改善",
        "latestLogLoss": 1.02,
        "previousLogLoss": 1.04,
        "logLossChange": -0.02,
        "profileCount": 2,
        "comparison": {"status": "comparable", "label": "样本可比", "sampleRatio": 1.066667},
        "affectsDecisionPath": False,
    }


def test_marks_single_profile_trend_as_insufficient_history():
    trend = review_calibration_trend(
        [{"created_at": "2026-08-08T23:42:00", "log_loss_after": 1.02, "sample_count": 320}]
    )

    assert trend["status"] == "insufficient_history"
    assert trend["label"] == "历史不足"
    assert trend["comparison"]["status"] == "insufficient_history"
    assert trend["affectsDecisionPath"] is False


def test_marks_loss_change_as_not_comparable_when_sample_size_shifts_too_much():
    trend = review_calibration_trend(
        [
            {"created_at": "2026-08-01T23:42:00", "log_loss_after": 1.04, "sample_count": 100},
            {"created_at": "2026-08-08T23:42:00", "log_loss_after": 1.02, "sample_count": 320},
        ]
    )

    assert trend["status"] == "improving"
    assert trend["comparison"] == {
        "status": "sample_changed",
        "label": "样本变化较大",
        "sampleRatio": 3.2,
    }
    assert trend["affectsDecisionPath"] is False
