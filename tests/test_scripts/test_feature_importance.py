import sys
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from scripts import feature_importance


class FakeClassifier:
    feature_importances_ = np.array([1.0])

    def fit(self, _features, _labels) -> None:
        return None

    def score(self, _features, _labels) -> float:
        return 1.0

    def predict_proba(self, _features) -> np.ndarray:
        return np.array([[0.2, 0.3, 0.5]])


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, *_args) -> None:
        return None

    def fetchone(self):
        return (88, "主队", "客队", *([1.0] * len(feature_importance.FEATURE_COLUMNS)))


class FakeConnection:
    def cursor(self) -> FakeCursor:
        return FakeCursor()


def test_training_defers_shap_explainer_until_prediction_explanation(monkeypatch) -> None:
    classifier = FakeClassifier()
    classifier_factory = Mock(return_value=classifier)
    build_explainer = Mock()
    monkeypatch.setitem(
        sys.modules,
        "xgboost",
        SimpleNamespace(XGBClassifier=classifier_factory),
    )
    monkeypatch.setattr(
        feature_importance,
        "_load_training_data",
        lambda _conn: (
            np.ones((3, 1)),
            np.array([0, 1, 2]),
            [1, 2, 3],
            ["home_elo"],
        ),
    )
    monkeypatch.setattr(feature_importance, "_compute_permutation_importance", lambda *_args: {})
    monkeypatch.setattr(feature_importance, "_build_shap_explainer", build_explainer)

    result = feature_importance.train_if_needed(object(), force=True)

    assert result["status"] == "ok"
    assert classifier_factory.call_args.kwargs["n_jobs"] == 1
    build_explainer.assert_not_called()


def test_permutation_importance_avoids_process_overhead_for_small_feature_sets(monkeypatch) -> None:
    import sklearn.inspection

    permutation = Mock(
        return_value=SimpleNamespace(
            importances_mean=np.array([0.2]),
            importances_std=np.array([0.01]),
        )
    )
    monkeypatch.setattr(sklearn.inspection, "permutation_importance", permutation)

    feature_importance._compute_permutation_importance(
        FakeClassifier(),
        np.ones((3, 1)),
        np.array([0, 1, 2]),
        ["home_elo"],
    )

    assert permutation.call_args.kwargs["n_jobs"] == 1


def test_prediction_stays_available_when_optional_shap_setup_fails(monkeypatch) -> None:
    monkeypatch.setattr(feature_importance, "_trained_model", FakeClassifier())
    monkeypatch.setattr(feature_importance, "_trained_explainer", None)
    monkeypatch.setattr(feature_importance, "_explainer_initialized", False)
    monkeypatch.setattr(
        feature_importance,
        "_feature_names_cache",
        [feature_importance.FEATURE_COLUMNS[0]],
    )
    monkeypatch.setattr(feature_importance, "train_if_needed", lambda _conn: {"status": "ok"})
    monkeypatch.setattr(
        feature_importance,
        "_build_shap_explainer",
        Mock(side_effect=RuntimeError("SHAP unavailable")),
    )

    result = feature_importance.explain_prediction(FakeConnection(), match_id=88)

    assert result["status"] == "ok"
    assert result["shap_values"] == []
    assert result["predicted_probs"] == {"home": 0.5, "draw": 0.3, "away": 0.2}
