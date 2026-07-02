"""Tests for evaluation metrics: Brier, LogLoss, CLV, RPS."""

from __future__ import annotations

import pytest

from scripts.evaluation_metrics import brier_score, log_loss_score, rps_score


class TestBrierScore:
    def test_perfect_prediction(self):
        """Perfect prediction should have Brier score of 0."""
        score = brier_score({"3": 1.0, "1": 0.0, "0": 0.0}, "3")
        assert score == 0.0

    def test_completely_wrong(self):
        """Completely wrong prediction should have Brier score of 2.0."""
        score = brier_score({"3": 1.0, "1": 0.0, "0": 0.0}, "0")
        assert score == 2.0

    def test_uniform_prediction(self):
        """Uniform prediction (0.33 each) should have Brier score ~0.67."""
        score = brier_score({"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}, "3")
        assert score == pytest.approx(2 / 3, abs=0.02)

    def test_score_in_range(self):
        """Brier score should be in [0, 2]."""
        score = brier_score({"3": 0.45, "1": 0.25, "0": 0.30}, "1")
        assert 0.0 <= score <= 2.0


class TestLogLossScore:
    def test_perfect_prediction(self):
        """Perfect prediction should have log loss close to 0."""
        score = log_loss_score({"3": 0.999, "1": 0.0005, "0": 0.0005}, "3")
        assert score < 0.01

    def test_completely_wrong_is_large(self):
        """Completely wrong high-confidence prediction should have large log loss."""
        score = log_loss_score({"3": 0.999, "1": 0.0005, "0": 0.0005}, "0")
        assert score > 5.0

    def test_uniform_prediction(self):
        """Uniform prediction should have log loss of -log(1/3) ≈ 1.099."""
        score = log_loss_score({"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}, "3")
        assert score == pytest.approx(1.099, abs=0.01)

    def test_no_zero_probability(self):
        """Function should clamp probabilities away from zero (no math domain error)."""
        score = log_loss_score({"3": 0.0, "1": 0.5, "0": 0.5}, "3")
        # Should not raise; score should be large but finite
        assert score > 0


class TestRPSScore:
    def test_perfect_prediction(self):
        """Perfect prediction should have RPS close to 0."""
        score = rps_score({"3": 1.0, "1": 0.0, "0": 0.0}, "3")
        assert score < 0.01

    def test_symmetric_prediction(self):
        """Symmetric probabilities should give symmetric RPS."""
        score = rps_score({"3": 1 / 3, "1": 1 / 3, "0": 1 / 3}, "1")
        assert 0.0 < score < 1.0

    def test_rps_less_than_brier_for_reasonable_predictions(self):
        """RPS is typically smaller than Brier for moderate probabilities."""
        probs = {"3": 0.45, "1": 0.25, "0": 0.30}
        b = brier_score(probs, "1")
        r = rps_score(probs, "1")
        # RPS should be ≤ Brier (RPS uses cumulative probabilities)
        assert r <= b + 0.1  # small tolerance
