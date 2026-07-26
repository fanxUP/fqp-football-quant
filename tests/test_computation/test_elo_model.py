"""Tests for Elo rating model."""

from __future__ import annotations

from scripts.elo_model import (
    DEFAULT_K,
    ELO_SCALE,
    HOME_ADVANTAGE,
    elo_to_1x2,
    expected_score,
    expected_score_with_home,
    update_elo,
)


class TestExpectedScore:
    def test_equal_ratings(self):
        """Two equal-rated teams should have 0.5 expected score each."""
        score = expected_score(1500, 1500)
        assert score == 0.5

    def test_stronger_team(self):
        """Higher-rated team should have >0.5 expected score."""
        score = expected_score(1600, 1400)
        assert score > 0.5

    def test_weaker_team(self):
        """Lower-rated team should have <0.5 expected score."""
        score = expected_score(1400, 1600)
        assert score < 0.5

    def test_400_point_difference(self):
        """400 Elo point difference ≈ 10x odds ratio, implying ~0.909 expected."""
        score = expected_score(2000, 1600)
        assert 0.85 < score < 0.95

    def test_home_advantage_increases_score(self):
        """Home advantage should boost expected score."""
        neutral = expected_score(1500, 1500)
        home = expected_score_with_home(1500, 1500)
        assert home > neutral

    def test_home_advantage_positive(self):
        """HOME_ADVANTAGE should be positive."""
        assert HOME_ADVANTAGE > 0


class TestUpdateElo:
    def test_home_win_increases_elo(self):
        """Home win should increase home Elo and the delta should be positive."""
        delta = update_elo(1500, 1500, result=1.0, goal_diff=0, is_home=True) - 1500
        assert delta > 0

    def test_away_win_increases_elo(self):
        """Away win should increase away Elo more (upset bonus)."""
        delta = update_elo(1500, 1600, result=1.0, goal_diff=0, is_home=False) - 1500
        assert delta > 0

    def test_draw_converges_ratings(self):
        """Draw should move ratings toward each other."""
        new_home = update_elo(1600, 1400, result=0.5, goal_diff=0, is_home=True)
        new_away = update_elo(1400, 1600, result=0.5, goal_diff=0, is_home=False)
        # Higher-rated team loses points on draw
        assert new_home < 1600
        # Lower-rated team gains points on draw
        assert new_away > 1400

    def test_goal_diff_increases_delta(self):
        """Larger goal difference should produce larger Elo change."""
        delta_1 = update_elo(1500, 1500, result=1.0, goal_diff=1, is_home=True) - 1500
        delta_3 = update_elo(1500, 1500, result=1.0, goal_diff=3, is_home=True) - 1500
        assert delta_3 > delta_1

    def test_higher_k_increases_delta(self):
        """Higher K-factor should produce larger Elo change."""
        delta_k32 = (
            update_elo(1500, 1500, result=1.0, goal_diff=0, k_factor=32, is_home=True) - 1500
        )
        delta_k16 = (
            update_elo(1500, 1500, result=1.0, goal_diff=0, k_factor=16, is_home=True) - 1500
        )
        assert delta_k32 > delta_k16

    def test_loss_decreases_elo(self):
        """Loss should decrease Elo for the losing team."""
        new_elo = update_elo(1500, 1500, result=0.0, goal_diff=0, is_home=True)
        assert new_elo < 1500


class TestEloScale:
    def test_elo_scale_is_400(self):
        """Standard Elo uses 400 as the scaling factor."""
        assert ELO_SCALE == 400

    def test_default_k_is_reasonable(self):
        """Default K should be positive."""
        assert DEFAULT_K > 0


class TestEloTo1x2:
    def test_returns_three_options(self):
        """Should return probabilities for 3, 1, 0."""
        probs = elo_to_1x2(1500, 1500)
        assert "3" in probs
        assert "1" in probs
        assert "0" in probs

    def test_probabilities_sum_to_one(self):
        """Probabilities should sum to approximately 1.0."""
        probs = elo_to_1x2(1500, 1500)
        total = sum(probs.values())
        assert abs(total - 1.0) < 0.01

    def test_home_stronger_gives_higher_win_prob(self):
        """Stronger home team should have higher win probability."""
        probs = elo_to_1x2(1800, 1400)
        assert probs["3"] > probs["0"]

    def test_all_probabilities_positive(self):
        """All probabilities should be positive."""
        probs = elo_to_1x2(1500, 1500)
        for v in probs.values():
            assert v > 0
