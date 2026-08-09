"""Tests for the shared-goal bivariate Poisson score distribution."""

from __future__ import annotations

import pytest

from scripts.bivariate_poisson_model import bivariate_score_matrix
from scripts.poisson_model import derive_1x2


def test_bivariate_matrix_is_normalized_and_preserves_marginal_home_bias() -> None:
    matrix = bivariate_score_matrix(1.8, 0.9, 0.18, max_goals=7)

    assert sum(matrix.values()) == pytest.approx(1.0)
    probabilities = derive_1x2(matrix)
    assert probabilities["3"] > probabilities["0"]


def test_positive_shared_goal_component_increases_equal_score_probability() -> None:
    independent = bivariate_score_matrix(1.3, 1.3, 0.0, max_goals=7)
    correlated = bivariate_score_matrix(1.3, 1.3, 0.2, max_goals=7)

    assert correlated["1:1"] > independent["1:1"]


def test_bivariate_matrix_rejects_invalid_shared_goal_component() -> None:
    with pytest.raises(ValueError, match="shared_goal_component"):
        bivariate_score_matrix(1.0, 0.8, 0.8)
