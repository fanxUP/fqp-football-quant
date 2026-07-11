"""Unit tests for bankroll.py — Kelly criterion and stake sizing."""

from __future__ import annotations

from scripts.bankroll import StakeLimits, raw_kelly, suggested_stake


class TestRawKelly:
    def test_positive_ev_bet(self):
        """50% win prob at odds 2.5 → positive Kelly fraction."""
        k = raw_kelly(0.5, 2.5)
        assert k > 0

    def test_fair_bet_zero(self):
        """Fair bet (prob = 1/odds) → Kelly = 0."""
        k = raw_kelly(0.5, 2.0)
        assert k == 0.0

    def test_negative_ev_zero(self):
        """Negative EV → Kelly clamped to 0."""
        k = raw_kelly(0.4, 2.0)
        assert k == 0.0

    def test_odds_less_than_one(self):
        """Odds ≤ 1 → invalid, return 0."""
        k = raw_kelly(0.8, 1.0)
        assert k == 0.0

    def test_odds_just_above_one(self):
        """Edge case: odds just above 1."""
        k = raw_kelly(0.99, 1.01)
        assert k >= 0.0


class TestStakeLimits:
    def test_default_limits(self):
        limits = StakeLimits()
        assert limits.daily_remaining == 500
        assert limits.pool_remaining == 300
        assert limits.max_ticket_stake == 100
        assert limits.kelly_fraction == 0.25

    def test_custom_limits(self):
        limits = StakeLimits(
            daily_remaining=1000,
            pool_remaining=500,
            max_ticket_stake=200,
        )
        assert limits.daily_remaining == 1000
        assert limits.max_ticket_stake == 200


class TestSuggestedStake:
    def test_returns_positive_for_positive_ev(self):
        limits = StakeLimits()
        stake = suggested_stake(0.5, 2.5, limits)
        assert stake > 0

    def test_returns_zero_for_negative_ev(self):
        limits = StakeLimits()
        stake = suggested_stake(0.3, 2.5, limits)
        assert stake == 0.0

    def test_respects_daily_remaining_limit(self):
        limits = StakeLimits(daily_remaining=10)
        stake = suggested_stake(0.6, 3.0, limits)
        assert stake <= 10

    def test_respects_max_ticket_stake(self):
        limits = StakeLimits(
            daily_remaining=500,
            pool_remaining=1000,
            max_ticket_stake=50,
            max_match_exposure_remaining=500,
        )
        stake = suggested_stake(0.6, 3.0, limits)
        assert stake <= 50

    def test_respects_pool_remaining(self):
        limits = StakeLimits(pool_remaining=20, daily_remaining=500, max_ticket_stake=500)
        stake = suggested_stake(0.6, 3.0, limits)
        # Kelly fraction of pool_remaining
        assert stake <= 20

    def test_rounds_to_even_number(self):
        limits = StakeLimits()
        stake = suggested_stake(0.5, 2.5, limits)
        # round(stake / 2) * 2 should be even
        assert stake % 2 == 0
