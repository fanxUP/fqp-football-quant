import numpy as np

from scripts.mlp_shadow_model import (
    MlpShadowProfile,
    fit_temporal_holdout,
    probabilities_from_classifier,
)


class _Classifier:
    classes_ = [0, 1, 2]

    def predict_proba(self, rows):
        return [[0.2, 0.3, 0.5]]


def test_mlp_maps_outcomes_to_official_codes() -> None:
    profile = MlpShadowProfile("/tmp/mlp.joblib", ("home", "away"), 160, 40, 1.02)
    assert probabilities_from_classifier(_Classifier(), profile, {"home": 0.7, "away": 0.3}) == {
        "0": 0.2,
        "1": 0.3,
        "3": 0.5,
    }


def test_mlp_uses_chronological_holdout() -> None:
    rows = np.array([[float(index % 5), float((index * 3) % 7)] for index in range(150)])
    classifier, profile = fit_temporal_holdout(
        rows, np.array([index % 3 for index in range(150)]), ("first", "second")
    )
    assert classifier is not None
    assert (profile.training_matches, profile.validation_matches) == (120, 30)
