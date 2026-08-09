"""Safety tests for the logistic-regression shadow prediction model."""

from __future__ import annotations

import numpy as np

from scripts.logistic_shadow_model import (
    LogisticShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.2, 0.3, 0.5]]


def test_classifier_probabilities_keep_1x2_mapping_and_normalization() -> None:
    profile = LogisticShadowProfile(
        artifact_path="/tmp/logistic-shadow.joblib",
        feature_columns=("home_strength", "away_strength"),
        training_matches=160,
        validation_matches=40,
        validation_log_loss=1.02,
    )

    result = probabilities_from_classifier(
        _Classifier(), profile, {"home_strength": 0.7, "away_strength": 0.3}
    )

    assert result == {"0": 0.2, "1": 0.3, "3": 0.5}


def test_temporal_holdout_reports_only_later_validation_loss() -> None:
    rows = np.array([[float(index % 5), float((index * 3) % 7)] for index in range(150)])
    labels = np.array([index % 3 for index in range(150)])

    classifier, profile = fit_temporal_holdout(rows, labels, ("first", "second"))

    assert classifier is not None
    assert profile.training_matches == 120
    assert profile.validation_matches == 30
    assert profile.validation_log_loss > 0
