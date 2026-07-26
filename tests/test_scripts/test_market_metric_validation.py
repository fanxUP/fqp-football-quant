import pytest

from scripts.market_metric_validation import MarketMetricValidationError, validate_market


def test_valid_market_returns_all_metric_definitions():
    metrics = validate_market(
        model_probabilities={"3": 0.50, "1": 0.28, "0": 0.22},
        market_probabilities={"3": 0.45, "1": 0.29, "0": 0.26},
        odds_by_option={"3": 2.10, "1": 3.30, "0": 3.50},
        snapshot_ids={"3": 11, "1": 12, "0": 13},
    )

    assert metrics["3"].break_even_probability == pytest.approx(1 / 2.10)
    assert metrics["3"].market_edge == pytest.approx(0.05)
    assert metrics["3"].breakeven_edge == pytest.approx(0.50 - 1 / 2.10)
    assert metrics["3"].expected_value == pytest.approx(0.05)


@pytest.mark.parametrize(
    ("model_probabilities", "market_probabilities", "message"),
    [
        ({"3": 0.60, "1": 0.40, "0": 0.30}, {"3": 0.45, "1": 0.29, "0": 0.26}, "模型概率合计"),
        ({"3": 0.50, "1": 0.28, "0": 0.22}, {"3": 0.55, "1": 0.35, "0": 0.25}, "市场概率合计"),
    ],
)
def test_invalid_probability_distribution_fails_closed(
    model_probabilities, market_probabilities, message
):
    with pytest.raises(MarketMetricValidationError, match=message):
        validate_market(
            model_probabilities=model_probabilities,
            market_probabilities=market_probabilities,
            odds_by_option={"3": 2.10, "1": 3.30, "0": 3.50},
            snapshot_ids={"3": 11, "1": 12, "0": 13},
        )


def test_mismatched_option_or_snapshot_mapping_fails_closed():
    with pytest.raises(MarketMetricValidationError, match="结果代码不一致"):
        validate_market(
            model_probabilities={"3": 0.50, "1": 0.28, "0": 0.22},
            market_probabilities={"3": 0.45, "1": 0.29, "0": 0.26},
            odds_by_option={"3": 2.10, "1": 3.30, "0": 3.50},
            snapshot_ids={"3": 11, "1": 12},
        )


def test_complete_market_cannot_have_every_option_positive_ev():
    with pytest.raises(MarketMetricValidationError, match="全部结果均为正 EV"):
        validate_market(
            model_probabilities={"3": 0.34, "1": 0.33, "0": 0.33},
            market_probabilities={"3": 0.34, "1": 0.33, "0": 0.33},
            odds_by_option={"3": 4.0, "1": 4.0, "0": 4.0},
            snapshot_ids={"3": 11, "1": 12, "0": 13},
        )
