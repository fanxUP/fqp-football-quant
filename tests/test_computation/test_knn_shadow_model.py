"""Safety tests for the KNN pre-match shadow model."""

from __future__ import annotations

import numpy as np

from scripts.knn_shadow_model import (
    KnnShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.24, 0.29, 0.47]]


def test_knn_keeps_1x2_mapping_and_normalization() -> None:
    profile = KnnShadowProfile(
        artifact_path="/tmp/knn-shadow.joblib",
        feature_columns=("home_strength", "away_strength"),
        training_matches=160,
        validation_matches=40,
        validation_log_loss=1.02,
    )

    assert probabilities_from_classifier(
        _Classifier(), profile, {"home_strength": 0.7, "away_strength": 0.3}
    ) == {"0": 0.24, "1": 0.29, "3": 0.47}


def test_knn_uses_chronological_holdout() -> None:
    rows = np.array([[float(index % 5), float((index * 3) % 7)] for index in range(150)])
    labels = np.array([index % 3 for index in range(150)])

    classifier, profile = fit_temporal_holdout(rows, labels, ("first", "second"))

    assert classifier is not None
    assert profile.training_matches == 120
    assert profile.validation_matches == 30
    assert profile.validation_log_loss > 0
