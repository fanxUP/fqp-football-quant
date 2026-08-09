"""Safety tests for the AdaBoost pre-match shadow model."""

from __future__ import annotations

import numpy as np

from scripts.adaboost_shadow_model import (
    AdaBoostShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.18, 0.26, 0.56]]


def test_adaboost_keeps_1x2_mapping_and_normalization() -> None:
    profile = AdaBoostShadowProfile(
        artifact_path="/tmp/adaboost-shadow.joblib",
        feature_columns=("home_strength", "away_strength"),
        training_matches=160,
        validation_matches=40,
        validation_log_loss=1.02,
    )

    assert probabilities_from_classifier(
        _Classifier(), profile, {"home_strength": 0.7, "away_strength": 0.3}
    ) == {"0": 0.18, "1": 0.26, "3": 0.56}


def test_adaboost_uses_chronological_holdout() -> None:
    rows = np.array([[float(index % 5), float((index * 3) % 7)] for index in range(150)])
    labels = np.array([index % 3 for index in range(150)])

    classifier, profile = fit_temporal_holdout(rows, labels, ("first", "second"))

    assert classifier is not None
    assert profile.training_matches == 120
    assert profile.validation_matches == 30
    assert profile.validation_log_loss > 0
