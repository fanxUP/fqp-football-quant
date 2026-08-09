"""Safety tests for the over-dispersed negative-binomial score model."""

from __future__ import annotations

import pytest

from scripts.negative_binomial_model import negative_binomial_score_matrix
from scripts.poisson_model import derive_1x2


def test_negative_binomial_matrix_is_normalized_and_preserves_home_bias() -> None:
    matrix = negative_binomial_score_matrix(1.8, 0.9, dispersion=0.7)

    assert sum(matrix.values()) == pytest.approx(1.0)
    assert derive_1x2(matrix)["3"] > derive_1x2(matrix)["0"]


def test_lower_dispersion_has_heavier_high_score_tail_than_near_poisson() -> None:
    dispersed = negative_binomial_score_matrix(1.5, 1.0, dispersion=0.5)
    near_poisson = negative_binomial_score_matrix(1.5, 1.0, dispersion=1000.0)

    assert dispersed["5:3"] > near_poisson["5:3"]


def test_negative_binomial_matrix_rejects_invalid_rates_or_dispersion() -> None:
    with pytest.raises(ValueError, match="dispersion"):
        negative_binomial_score_matrix(1.2, 0.8, dispersion=0)
