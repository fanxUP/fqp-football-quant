"""Tests for motivation score computation."""
from __future__ import annotations

from scripts.features.build_motivation_score import compute_motivation_score


class TestComputeMotivationScore:
    def test_neutral_context_returns_zero(self):
        """Empty context should return 0.0."""
        score = compute_motivation_score({})
        assert score == 0.0

    def test_returns_float(self):
        """Should return a float."""
        score = compute_motivation_score({"objective_necessity": 50})
        assert isinstance(score, float)

    def test_high_necessity_gives_positive_score(self):
        """High objective necessity should produce positive score."""
        score = compute_motivation_score({"objective_necessity": 80})
        assert score > 0

    def test_must_win_adds_bonus(self):
        """must_win flag should add 10 points."""
        base = compute_motivation_score({"objective_necessity": 50})
        boosted = compute_motivation_score({"objective_necessity": 50, "must_win": True})
        assert boosted > base

    def test_already_qualified_reduces_score(self):
        """already_qualified should reduce score by 15."""
        base = compute_motivation_score({"objective_necessity": 80})
        reduced = compute_motivation_score({"objective_necessity": 80, "already_qualified": True})
        assert reduced < base

    def test_already_eliminated_reduces_score(self):
        """already_eliminated should reduce score by 10."""
        base = compute_motivation_score({"objective_necessity": 60})
        reduced = compute_motivation_score({"objective_necessity": 60, "already_eliminated": True})
        assert reduced < base

    def test_score_clamped_to_100(self):
        """Score should never exceed 100."""
        score = compute_motivation_score({
            "objective_necessity": 100,
            "ranking_or_prize_value": 100,
            "home_derby_revenge": 100,
            "future_schedule_pressure_inverse": 100,
            "lineup_commitment_signal": 100,
            "must_win": True,
        })
        assert score <= 100

    def test_score_clamped_to_zero(self):
        """Score should never be negative."""
        score = compute_motivation_score({
            "already_qualified": True,
            "already_eliminated": True,
        })
        assert score >= 0

    def test_all_factors_contribute(self):
        """All five factors should contribute to the final score."""
        single = compute_motivation_score({"objective_necessity": 50})
        multi = compute_motivation_score({
            "objective_necessity": 50,
            "ranking_or_prize_value": 50,
            "home_derby_revenge": 50,
        })
        # More factors should produce a different (likely higher) score
        assert multi != single
