"""Unit tests for poisson_model.py — Poisson score matrix and 1x2 derivation."""

from __future__ import annotations

import math

from scripts.poisson_model import (
    derive_1x2,
    derive_total_goals,
    estimate_lambdas_from_odds,
    poisson_pmf,
    score_matrix,
)


class TestPoissonPMF:
    def test_k_zero(self):
        """P(X=0) = e^(-lambda)."""
        result = poisson_pmf(0, 2.0)
        assert abs(result - math.exp(-2.0)) < 1e-10

    def test_k_one(self):
        """P(X=1) = lambda * e^(-lambda)."""
        lam = 1.5
        result = poisson_pmf(1, lam)
        expected = lam * math.exp(-lam)
        assert abs(result - expected) < 1e-10

    def test_pmf_sums_to_approx_one(self):
        """Sum of PMF for k=0..20 should be close to 1."""
        lam = 2.0
        total = sum(poisson_pmf(k, lam) for k in range(21))
        assert abs(total - 1.0) < 0.001

    def test_higher_lambda_shifts_right(self):
        """Higher lambda → more probability mass at higher k."""
        p_low = poisson_pmf(0, 1.0)
        p_high = poisson_pmf(0, 3.0)
        assert p_high < p_low  # P(X=0) lower when more goals expected


class TestScoreMatrix:
    def test_all_scores_non_negative(self):
        matrix = score_matrix(1.5, 1.2)
        for prob in matrix.values():
            assert prob >= 0

    def test_sums_to_one(self):
        matrix = score_matrix(1.5, 1.2, max_goals=5)
        total = sum(matrix.values())
        assert abs(total - 1.0) < 1e-10

    def test_symmetric_when_equal_lambdas(self):
        matrix = score_matrix(1.5, 1.5, max_goals=3)
        # P(2:1) ≈ P(1:2) for equal lambdas
        assert abs(matrix.get("2:1", 0) - matrix.get("1:2", 0)) < 0.01

    def test_home_bias_when_higher_lambda(self):
        matrix = score_matrix(2.5, 0.8, max_goals=3)
        # Home win should be more likely than away win
        home_win = sum(
            p for score, p in matrix.items() if int(score.split(":")[0]) > int(score.split(":")[1])
        )
        away_win = sum(
            p for score, p in matrix.items() if int(score.split(":")[0]) < int(score.split(":")[1])
        )
        assert home_win > away_win

    def test_default_max_goals(self):
        matrix = score_matrix(1.5, 1.2)
        # Should have (max_goals+1)^2 entries = 64 for default max_goals=7
        assert len(matrix) == 64


class TestDerive1x2:
    def test_sums_to_one(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_1x2(matrix)
        total = sum(probs.values())
        assert abs(total - 1.0) < 1e-10

    def test_three_outcomes(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_1x2(matrix)
        assert set(probs.keys()) == {"3", "1", "0"}

    def test_all_non_negative(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_1x2(matrix)
        for p in probs.values():
            assert p >= 0


class TestDeriveTotalGoals:
    def test_sums_to_one(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_total_goals(matrix)
        total = sum(probs.values())
        assert abs(total - 1.0) < 1e-10

    def test_has_expected_keys(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_total_goals(matrix)
        for i in range(7):
            assert str(i) in probs
        assert "7+" in probs
        assert len(probs) == 8

    def test_total_goals_non_negative(self):
        matrix = score_matrix(1.5, 1.2)
        probs = derive_total_goals(matrix)
        for p in probs.values():
            assert p >= 0


class TestEstimateLambdas:
    def test_returns_reasonable_lambdas(self):
        """For typical 1x2 probabilities, lambdas should be positive and reasonable."""
        lam_h, lam_a = estimate_lambdas_from_odds(0.45, 0.25, 0.30)
        assert lam_h > 0
        assert lam_a > 0
        # Typical football goals ~0.5-3.0 per team
        assert 0.5 < lam_h < 3.5
        assert 0.5 < lam_a < 3.5

    def test_home_stronger_gives_higher_home_lambda(self):
        """When home is favored, lambda_home > lambda_away."""
        lam_h, lam_a = estimate_lambdas_from_odds(0.55, 0.25, 0.20)
        assert lam_h > lam_a

    def test_away_stronger_gives_higher_away_lambda(self):
        """When away is favored, lambda_away > lambda_home."""
        lam_h, lam_a = estimate_lambdas_from_odds(0.25, 0.25, 0.50)
        assert lam_a > lam_h

    def test_roughly_reproduces_input_probabilities(self):
        """Estimated lambdas should produce 1x2 probabilities close to input."""
        home_p, draw_p, away_p = 0.45, 0.25, 0.30
        lam_h, lam_a = estimate_lambdas_from_odds(home_p, draw_p, away_p)
        matrix = score_matrix(lam_h, lam_a)
        derived = derive_1x2(matrix)
        # Should be reasonably close (within ~0.1)
        assert abs(derived["3"] - home_p) < 0.15
        assert abs(derived["1"] - draw_p) < 0.15
        assert abs(derived["0"] - away_p) < 0.15
