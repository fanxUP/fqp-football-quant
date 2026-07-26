from __future__ import annotations

import math

import pytest

from scripts.upset.domain import (
    IncompleteMarketError,
    UpsetRule,
    calculate_market_signal,
    resolve_actual_option,
)


def test_calculates_normalized_probability_surprise_and_level():
    signal = calculate_market_signal(
        play_type="spf",
        odds_by_option={"3": 1.45, "1": 4.20, "0": 6.50},
        actual_result="A",
        rule=UpsetRule.default(),
    )

    expected_probability = (1 / 6.50) / ((1 / 1.45) + (1 / 4.20) + (1 / 6.50))
    assert signal.actual_option == "0"
    assert signal.actual_probability == pytest.approx(expected_probability)
    assert signal.surprise_bits == pytest.approx(-math.log2(expected_probability))
    assert signal.upset_level == "S"
    assert signal.market_favourite_option == "3"
    assert signal.favourite_failed is True


@pytest.mark.parametrize(
    ("probability", "expected"),
    [(0.1499, "S"), (0.15, "A"), (0.22, "B"), (0.30, "C"), (0.38, None)],
)
def test_level_boundaries_are_stable(probability: float, expected: str | None):
    assert UpsetRule.default().classify(probability) == expected


def test_high_cardinality_markets_use_stricter_probability_thresholds():
    rule = UpsetRule.default()

    assert rule.classify(0.10, "bf") is None
    assert rule.classify(0.015, "bf") == "B"
    assert rule.classify(0.05, "bqc") == "B"
    assert rule.classify(0.08, "zjq") == "B"


def test_normal_result_is_not_mislabeled_as_upset():
    signal = calculate_market_signal(
        play_type="spf",
        odds_by_option={"3": 1.80, "1": 3.20, "0": 4.40},
        actual_result="H",
        rule=UpsetRule.default(),
    )

    assert signal.actual_option == "3"
    assert signal.upset_level is None
    assert signal.favourite_failed is False


def test_resolves_every_supported_official_result_format():
    assert resolve_actual_option("spf", "H", {"3", "1", "0"}) == "3"
    assert resolve_actual_option("rqspf", "a", {"3", "1", "0"}) == "0"
    assert resolve_actual_option("zjq", "7+", {str(value) for value in range(8)}) == "7"
    assert (
        resolve_actual_option("bqc", "H/A", {"33", "31", "30", "13", "11", "10", "03", "01", "00"})
        == "30"
    )
    assert resolve_actual_option("bf", "2-1", {"2:1", "other_h"}) == "2:1"


def test_maps_unlisted_score_to_correct_other_bucket():
    options = {"1:0", "0:0", "0:1", "other_h", "other_d", "other_a"}

    assert resolve_actual_option("bf", "8:1", options) == "other_h"
    assert resolve_actual_option("bf", "5:5", options) == "other_d"
    assert resolve_actual_option("bf", "1:8", options) == "other_a"


def test_rejects_incomplete_market_instead_of_fabricating_probability():
    with pytest.raises(IncompleteMarketError, match="spf.*3"):
        calculate_market_signal(
            play_type="spf",
            odds_by_option={"3": 1.80, "1": 3.20},
            actual_result="3",
            rule=UpsetRule.default(),
        )


def test_rejects_market_when_actual_result_cannot_be_mapped():
    with pytest.raises(IncompleteMarketError, match="实际赛果"):
        calculate_market_signal(
            play_type="zjq",
            odds_by_option={str(value): 5.0 + value for value in range(8)},
            actual_result=None,
            rule=UpsetRule.default(),
        )
