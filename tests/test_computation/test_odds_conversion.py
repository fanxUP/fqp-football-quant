"""Tests for odds conversion and debiasing functions."""

from __future__ import annotations

import pytest

from scripts.odds_conversion import (
    full_debias_pipeline,
    implied_probabilities,
    normalize_probabilities,
    overround,
    power_method,
    shin_method,
)


class TestImpliedProbabilities:
    def test_basic_conversion(self):
        result = implied_probabilities({"3": 2.0, "1": 3.5, "0": 4.0})
        assert result["3"] == 0.5
        assert result["1"] == pytest.approx(1.0 / 3.5)
        assert result["0"] == 0.25

    def test_skips_zero_odds(self):
        result = implied_probabilities({"3": 2.0, "1": 0, "0": 4.0})
        assert "1" not in result
        assert len(result) == 2

    def test_skips_none_odds(self):
        result = implied_probabilities({"3": 2.0, "1": None, "0": 4.0})
        assert "1" not in result


class TestNormalizeProbabilities:
    def test_sums_to_one(self):
        result = normalize_probabilities({"3": 2.0, "1": 3.5, "0": 4.0})
        assert sum(result.values()) == pytest.approx(1.0)

    def test_preserves_order(self):
        """Favorite should remain favorite after normalization."""
        odds = {"3": 1.8, "1": 3.5, "0": 5.0}
        result = normalize_probabilities(odds)
        assert result["3"] > result["1"] > result["0"]

    def test_raises_on_invalid_odds(self):
        with pytest.raises(ValueError):
            normalize_probabilities({"3": 0, "1": 0, "0": 0})


class TestOverround:
    def test_overround_positive_for_market_odds(self):
        """Market odds should have overround > 0 (margin exists)."""
        o = overround({"3": 1.8, "1": 3.5, "0": 5.0})
        assert o > 0.0

    def test_overround_is_float(self):
        o = overround({"3": 2.0, "1": 3.5, "0": 4.0})
        assert isinstance(o, float)


class TestShinMethod:
    def test_probabilities_sum_to_one(self):
        odds = {"3": 1.8, "1": 3.5, "0": 5.0}
        result = shin_method(odds)
        assert sum(result.values()) == pytest.approx(1.0)

    def test_all_probabilities_positive(self):
        odds = {"3": 1.8, "1": 3.5, "0": 5.0}
        result = shin_method(odds)
        for v in result.values():
            assert v > 0

    def test_two_outcome_market(self):
        """Should handle two-outcome markets (e.g., over/under)."""
        result = shin_method({"over": 1.9, "under": 1.9})
        assert sum(result.values()) == pytest.approx(1.0)


class TestPowerMethod:
    def test_default_power_equals_normalize(self):
        """power=1.0 should be equivalent to normalize_probabilities."""
        odds = {"3": 1.8, "1": 3.5, "0": 5.0}
        result = power_method(odds, power=1.0)
        expected = normalize_probabilities(odds)
        for k in result:
            assert result[k] == pytest.approx(expected[k])

    def test_small_power_flattens(self):
        """power < 1 should reduce differences between probabilities."""
        odds = {"3": 1.5, "1": 4.0, "0": 8.0}
        flat = power_method(odds, power=0.5)
        normal = power_method(odds, power=1.0)
        # Flattened distribution should have smaller max-min range
        flat_range = max(flat.values()) - min(flat.values())
        normal_range = max(normal.values()) - min(normal.values())
        assert flat_range < normal_range


class TestFullDebiasPipeline:
    def test_returns_correct_keys(self):
        result = full_debias_pipeline({"3": 1.8, "1": 3.5, "0": 5.0})
        assert "shin" in result
        assert "flb_corrected" in result

    def test_flb_corrected_sums_to_one(self):
        result = full_debias_pipeline({"3": 1.8, "1": 3.5, "0": 5.0})
        assert sum(result["flb_corrected"].values()) == pytest.approx(1.0)

    def test_handles_two_outcome(self):
        """Should handle two-outcome markets gracefully."""
        result = full_debias_pipeline({"over": 1.9, "under": 1.9})
        assert len(result["flb_corrected"]) == 2
