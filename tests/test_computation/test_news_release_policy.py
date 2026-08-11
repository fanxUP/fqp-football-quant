from scripts.news_release_policy import assess_promotion


def test_promotion_requires_enough_settled_samples() -> None:
    assessment = assess_promotion(
        sample_size=999,
        brier_delta=-0.02,
        log_loss_delta=-0.02,
    )

    assert assessment["eligible"] is False
    assert "1000" in assessment["reason"]


def test_promotion_requires_both_metrics_to_not_regress() -> None:
    assessment = assess_promotion(
        sample_size=1200,
        brier_delta=-0.01,
        log_loss_delta=0.001,
    )

    assert assessment["eligible"] is False
    assert "Log Loss" in assessment["reason"]


def test_promotion_is_eligible_only_after_material_brier_improvement() -> None:
    assessment = assess_promotion(
        sample_size=1200,
        brier_delta=-0.006,
        log_loss_delta=-0.001,
    )

    assert assessment["eligible"] is True
