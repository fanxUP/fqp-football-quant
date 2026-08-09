"""Safety tests for the Gaussian naive-Bayes pre-match shadow model."""

from __future__ import annotations

import numpy as np

from scripts.naive_bayes_shadow_model import (
    NaiveBayesShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.16, 0.24, 0.60]]


def test_naive_bayes_keeps_official_1x2_mapping() -> None:
    profile = NaiveBayesShadowProfile(
        artifact_path="/tmp/naive-bayes-shadow.joblib",
        feature_columns=("home_strength", "away_strength"),
        training_matches=160,
        validation_matches=40,
        validation_log_loss=1.02,
    )

    assert probabilities_from_classifier(
        _Classifier(), profile, {"home_strength": 0.7, "away_strength": 0.3}
    ) == {"0": 0.16, "1": 0.24, "3": 0.6}


def test_naive_bayes_uses_only_later_rows_for_validation() -> None:
    rows = np.array([[float(index % 5), float((index * 3) % 7)] for index in range(150)])
    labels = np.array([index % 3 for index in range(150)])

    classifier, profile = fit_temporal_holdout(rows, labels, ("first", "second"))

    assert classifier is not None
    assert profile.training_matches == 120
    assert profile.validation_matches == 30
    assert profile.validation_log_loss > 0
