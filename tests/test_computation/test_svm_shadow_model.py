"""Safety tests for the RBF support-vector pre-match shadow model."""

from __future__ import annotations

import numpy as np

from scripts.svm_shadow_model import (
    SvmShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        assert len(rows) == 1
        return [[0.1, 0.3, 0.6]]


def test_svm_keeps_official_1x2_mapping() -> None:
    profile = SvmShadowProfile("/tmp/svm.joblib", ("home", "away"), 160, 40, 1.0)
    assert probabilities_from_classifier(_Classifier(), profile, {"home": 0.7, "away": 0.3}) == {
        "0": 0.1, "1": 0.3, "3": 0.6,
    }


def test_svm_evaluates_later_chronological_holdout() -> None:
    rows = np.array([[float(i % 5), float((i * 3) % 7)] for i in range(150)])
    labels = np.array([i % 3 for i in range(150)])
    classifier, profile = fit_temporal_holdout(rows, labels, ("first", "second"))
    assert classifier is not None
    assert (profile.training_matches, profile.validation_matches) == (120, 30)
    assert profile.validation_log_loss > 0
