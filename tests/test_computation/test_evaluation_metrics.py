"""Tests for evaluation metrics: Brier, LogLoss, CLV, RPS."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.evaluation_metrics import brier_score, compute_match_metrics, log_loss_score, rps_score


def test_evaluation_script_can_start_outside_project_without_pythonpath(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts/evaluation_metrics.py"
    completed = subprocess.run(
        [sys.executable, "-I", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Brier Score:" in completed.stdout


@pytest.mark.parametrize("bad", [None, -0.1, 1.1, float("nan"), float("inf"), "bad", True])
def test_complete_evaluation_rejects_invalid_model_probability(bad):
    with pytest.raises(ValueError):
        compute_match_metrics({"3": bad, "1": 0.2, "0": 0.1}, {}, "3")


@pytest.mark.parametrize(
    "probs",
    [{"3": 0.7}, {"3": 0.7, "1": 0.7, "0": 0.7}, {"3": 0.7, "1": 0.2, "0": 0.1, "unknown": 0.0}],
)
def test_complete_evaluation_rejects_incomplete_or_incoherent_model_vector(probs):
    with pytest.raises(ValueError):
        compute_match_metrics(probs, {}, "3")


@pytest.mark.parametrize("bad", [None, -0.1, 1.1, float("nan"), float("inf"), "bad", True])
def test_missing_market_does_not_block_independent_evaluation(bad):
    model = {"3": 0.7, "1": 0.2, "0": 0.1}
    closing = {"3": 0.5, "1": 0.3, "0": 0.2}
    result = compute_match_metrics(
        model, {"3": bad, "1": 0.35, "0": 0.25}, "3", closing_market_probs=closing
    )
    assert result["brier_score"] == 0.14
    assert result["log_loss"] > 0 and result["rps"] >= 0
    assert result["market_probability"] is None
    assert result["clv_score"] is result["market_probability_move"] is None
    assert all(result[f"gap_{option}"] is None for option in model)
    assert result["closing_edge"] == 0.2


@pytest.mark.parametrize("bad", [None, 0.0, 1.0, -1.0, float("nan"), float("inf"), "bad"])
def test_bad_optional_closing_odds_stay_unknown(bad):
    result = compute_match_metrics({"3": 0.7, "1": 0.2, "0": 0.1}, {}, "3", closing_odds={"3": bad})
    assert result["official_sp"] is result["ev"] is None
    assert result["brier_score"] == 0.14


def test_probability_boundaries_and_rounding_are_preserved():
    perfect = compute_match_metrics(
        {"3": 1.0, "1": 0.0, "0": 0.0}, {"3": 0.0, "1": 0.6, "0": 0.4}, "3"
    )
    assert perfect["brier_score"] == 0 and perfect["market_probability"] == 0
    rounded = compute_match_metrics({option: 0.333333 for option in ("3", "1", "0")}, {}, "1")
    assert rounded["model_probability"] == 0.333333  # Never silently renormalize.


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
