"""Tests for travel feature computation."""

from __future__ import annotations

import pytest

from scripts.features.build_travel_features import haversine_km


class TestHaversineKm:
    def test_same_point_zero(self):
        """Distance from a point to itself should be 0."""
        d = haversine_km(51.556, -0.279, 51.556, -0.279)
        assert d == 0.0

    def test_known_distance(self):
        """Known distance: London (Wembley) to Manchester (Old Trafford) ≈ 260 km."""
        # Wembley: 51.556, -0.279
        # Old Trafford: 53.463, -2.291
        d = haversine_km(51.556, -0.279, 53.463, -2.291)
        assert 250 < d < 280

    def test_long_distance(self):
        """Beijing to London should be ~8,100 km."""
        # Beijing: 39.904, 116.407
        # London: 51.507, -0.128
        d = haversine_km(39.904, 116.407, 51.507, -0.128)
        assert 7500 < d < 8500

    def test_returns_float(self):
        d = haversine_km(40.0, -3.0, 48.0, 2.0)
        assert isinstance(d, float)

    def test_distance_positive(self):
        """Distance between different points should be positive."""
        d = haversine_km(40.0, -3.0, 41.0, -3.0)
        assert d > 0

    def test_symmetric(self):
        """Distance should be symmetric."""
        d1 = haversine_km(51.5, -0.1, 48.8, 2.3)
        d2 = haversine_km(48.8, 2.3, 51.5, -0.1)
        assert d1 == pytest.approx(d2)

    def test_short_distance(self):
        """Short distance (< 10 km) should be reasonable."""
        # Two nearby London locations
        d = haversine_km(51.500, -0.120, 51.510, -0.125)
        assert 0 < d < 2
