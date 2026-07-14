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


class EvaluationCursor:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self._result_index = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, *_args) -> None:
        self.queries.append(" ".join(query.split()))

    @property
    def description(self):
        if self._result_index == 0:
            return [
                ("model_name",), ("n",), ("avg_brier",),
                ("avg_logloss",), ("avg_rps",), ("avg_clv",),
            ]
        return [("total_evaluated",), ("overall_brier",), ("overall_logloss",)]

    def fetchall(self):
        self._result_index = 1
        return [("elo_rating", 12, 0.61, 1.01, 0.20, 0.03)]

    def fetchone(self):
        return (12, 0.61, 1.01)


class EvaluationConnection:
    def __init__(self) -> None:
        self.cursor_instance = EvaluationCursor()

    def cursor(self) -> EvaluationCursor:
        return self.cursor_instance


class CaptureTrainingCursor:
    def __init__(self) -> None:
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = " ".join(query.split())

    def fetchall(self):
        return []


class CaptureTrainingConnection:
    def __init__(self) -> None:
        self.cursor_instance = CaptureTrainingCursor()

    def cursor(self) -> CaptureTrainingCursor:
        return self.cursor_instance


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


def test_evaluation_summary_assigns_metrics_directly_to_their_model_version() -> None:
    conn = EvaluationConnection()

    result = feature_importance.get_evaluation_summary(conn)

    assert result["models"][0]["n"] == 12
    summary_query = conn.cursor_instance.queries[0]
    assert "DISTINCT ON (source_mem.match_id, source_mem.model_version_id)" in summary_query
    assert "JOIN model_versions mv ON mv.id = mem.model_version_id" in summary_query
    assert "JOIN model_predictions" not in summary_query


def test_feature_training_uses_one_pre_match_snapshot_per_match() -> None:
    conn = CaptureTrainingConnection()

    result = feature_importance._load_training_data(conn, min_samples=1)

    assert result is None
    query = conn.cursor_instance.query
    assert "DISTINCT ON (fs.match_id)" in query
    assert "fs.snapshot_time < m.kickoff_time" in query
