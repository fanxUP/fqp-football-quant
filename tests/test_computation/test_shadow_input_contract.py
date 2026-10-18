"""Fixed-sample model input compatibility; no application DB or provider calls."""

from __future__ import annotations

import importlib
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import joblib
import numpy as np
import pytest

from scripts import feature_importance, prematch_feature_dataset, shadow_training
from scripts.feature_schema import CURRENT_SNAPSHOT_VERSION, FEATURE_COLUMNS, FEATURE_SCHEMA_VERSION

MODELS = (
    "logistic",
    "xgboost",
    "random_forest",
    "extra_trees",
    "hist_gradient_boosting",
    "adaboost",
    "lda",
    "knn",
    "mlp",
    "naive_bayes",
    "svm",
)
COLUMNS = ("home_lineup_confirmed", "home_team_market_value", "rest_days_diff")


def parameters():
    return {
        "rollout_mode": "shadow",
        "artifact_path": "/unused/shadow-model",
        "feature_columns": list(COLUMNS),
        "training_matches": 160,
        "validation_matches": 40,
        "validation_log_loss": 1.02,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_input_policy": "snapshot-columns/v1",
    }


class Classifier:
    classes_ = np.array([0, 1, 2])
    n_features_in_ = 3
    feature_names_in_ = np.array(COLUMNS)

    def __init__(self):
        self.rows = []

    def load_model(self, _path):
        pass

    def predict_proba(self, rows):
        self.rows.append(np.asarray(rows, dtype=float))
        return np.array([[0.2, 0.3, 0.5]])


def loader(monkeypatch, model, classifier):
    module = importlib.import_module(f"scripts.{model}_shadow_model")
    artifact_load = Mock(return_value=classifier)
    if model == "xgboost":
        import xgboost

        monkeypatch.setattr(xgboost, "XGBClassifier", artifact_load)
    else:
        monkeypatch.setattr(joblib, "load", artifact_load)
    return module.load_probabilities, artifact_load


def snapshot():
    return {
        "feature_version": CURRENT_SNAPSHOT_VERSION,
        "home_lineup_confirmed": False,
        "home_team_market_value": 0.6,
        "rest_days_diff": None,
        "unselected": 999,
    }


@pytest.mark.parametrize("model", MODELS)
def test_unversioned_artifact_is_disabled_before_loading(monkeypatch, model):
    classifier = Classifier()
    load, artifact_load = loader(monkeypatch, model, classifier)
    legacy = parameters()
    legacy.pop("feature_schema_version")
    legacy.pop("feature_input_policy")
    assert load(legacy, snapshot()) is None
    artifact_load.assert_not_called()
    assert classifier.rows == []


@pytest.mark.parametrize("model", MODELS)
def test_all_loaders_use_only_saved_order_and_normalize_missing(monkeypatch, model):
    classifier = Classifier()
    load, _ = loader(monkeypatch, model, classifier)
    assert load(parameters(), snapshot()) == {"0": 0.2, "1": 0.3, "3": 0.5}
    np.testing.assert_allclose(classifier.rows[0], [[0.0, 0.6, np.nan]], equal_nan=True)


@pytest.mark.parametrize("model", ("logistic", "xgboost", "random_forest"))
@pytest.mark.parametrize("mismatch", ("width", "order", "unknown_width"))
def test_artifact_shape_and_names_must_match_profile(monkeypatch, model, mismatch):
    classifier = Classifier()
    if mismatch == "width":
        classifier.n_features_in_ = 55
    elif mismatch == "order":
        classifier.feature_names_in_ = np.array(COLUMNS[::-1])
    else:
        classifier.n_features_in_ = None
    load, _ = loader(monkeypatch, model, classifier)
    assert load(parameters(), snapshot()) is None
    assert classifier.rows == []


@pytest.mark.parametrize(
    "override",
    (
        {"feature_schema_version": "future/v2"},
        {"feature_schema_version": None},
        {"feature_input_policy": "guess/v2"},
        {"feature_input_policy": None},
        {"feature_columns": [COLUMNS[0], COLUMNS[0]]},
        {"feature_columns": ["unknown_column"]},
        {"feature_columns": []},
        {"feature_columns": COLUMNS[0]},
    ),
)
def test_invalid_contract_never_loads_artifact(monkeypatch, override):
    load, artifact_load = loader(monkeypatch, "logistic", Classifier())
    assert load(parameters() | override, snapshot()) is None
    artifact_load.assert_not_called()


@pytest.mark.parametrize("version", (None, "future-semantics/v2"))
def test_unknown_snapshot_semantics_disable_signal(monkeypatch, version):
    load, artifact_load = loader(monkeypatch, "logistic", Classifier())
    assert load(parameters(), snapshot() | {"feature_version": version}) is None
    artifact_load.assert_not_called()


@pytest.mark.parametrize("value", (float("inf"), float("-inf"), "invalid", "2.5", 0, True))
def test_input_values_are_finite_numeric_or_nan(monkeypatch, value):
    classifier = Classifier()
    load, _ = loader(monkeypatch, "logistic", classifier)
    assert load(parameters(), snapshot() | {COLUMNS[2]: value}) is not None
    actual = classifier.rows[0][0, 2]
    if value in ("2.5", 0, True):
        assert actual == float(value)
    else:
        assert np.isnan(actual)


def test_shared_training_persists_contract_without_promoting(tmp_path):
    columns = tuple(COLUMNS)
    classifier = Classifier()
    profile = SimpleNamespace(
        feature_columns=columns,
        training_matches=120,
        validation_matches=30,
        validation_log_loss=1.0,
    )
    store = Mock()
    result = shadow_training.train_shadow_with_connection(
        object(),
        load_dataset=lambda _: (
            np.ones((150, 3)),
            np.arange(150) % 3,
            ["2026-01-01", "2026-02-01"],
        ),
        fit_model=lambda *_: (classifier, profile),
        feature_columns=columns,
        resolve_artifact=lambda: tmp_path / "test.joblib",
        artifact_relative_path="test.joblib",
        model_name="test_shadow",
        missing_message="missing",
        store_profile=store,
        save_artifact=lambda _, path: path.write_bytes(b"fixed-fixture"),
    )
    assert result["status"] == "ok"
    saved = store.call_args.args[1]
    assert saved["feature_schema_version"] == FEATURE_SCHEMA_VERSION
    assert saved["feature_input_policy"] == "snapshot-columns/v1"
    assert saved["feature_columns"] == list(columns)
    assert saved["rollout_mode"] == "shadow"


@pytest.mark.parametrize("columns", ((COLUMNS[0], COLUMNS[0]), ("unknown",)))
def test_training_rejects_invalid_schema_before_fit_or_write(tmp_path, columns):
    fit = Mock()
    store = Mock()
    save = Mock()
    with pytest.raises(ValueError, match="feature"):
        shadow_training.train_shadow_with_connection(
            object(),
            load_dataset=lambda _: (np.ones((150, 2)), np.arange(150) % 3, ["date"]),
            fit_model=fit,
            feature_columns=columns,
            resolve_artifact=lambda: tmp_path / "none",
            artifact_relative_path="none",
            model_name="test",
            missing_message="missing",
            store_profile=store,
            save_artifact=save,
        )
    fit.assert_not_called()
    store.assert_not_called()
    save.assert_not_called()


def test_pipeline_roundtrip_keeps_train_fold_imputer_and_subset(monkeypatch):
    from scripts.logistic_shadow_model import fit_temporal_holdout, load_probabilities

    rows = np.array([[float(i % 5), float((i * 3) % 7), float(i % 2)] for i in range(150)])
    rows[::5, 1] = np.nan
    rows[120:, 1] = 99999  # Future holdout cannot set training median.
    fitted, _ = fit_temporal_holdout(rows, np.arange(150) % 3, COLUMNS)
    assert fitted.named_steps["imputer"].statistics_[1] == np.nanmedian(rows[:120, 1])
    buffer = io.BytesIO()
    joblib.dump(fitted, buffer)
    buffer.seek(0)
    restored = joblib.load(buffer)
    monkeypatch.setattr(joblib, "load", lambda _: restored)
    result = load_probabilities(parameters(), snapshot())
    direct = restored.predict_proba([[0.0, 0.6, np.nan]])[0]
    assert result == {"0": round(direct[0], 8), "1": round(direct[1], 8), "3": round(direct[2], 8)}


def test_explanation_training_keeps_native_nan_instead_of_median():
    conn = MagicMock()

    def row(mid, a, b):
        return (mid, "league", a, b, *([None] * (len(FEATURE_COLUMNS) - 2)), 0)

    conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        row(1, 1.0, None),
        row(2, None, 4.0),
        row(3, 3.0, 2.0),
    ]
    features, _, _, names = feature_importance._load_training_data(conn, min_samples=1)
    assert names == list(FEATURE_COLUMNS[:2])
    np.testing.assert_allclose(features, [[1, np.nan], [np.nan, 4], [3, 2]], equal_nan=True)


def test_explanation_prediction_keeps_native_nan_and_real_zero(monkeypatch):
    classifier = Classifier()
    monkeypatch.setattr(feature_importance, "_trained_model", classifier)
    monkeypatch.setattr(feature_importance, "_feature_names_cache", list(FEATURE_COLUMNS[:3]))
    monkeypatch.setattr(feature_importance, "_explainer_initialized", True)
    monkeypatch.setattr(feature_importance, "_trained_explainer", None)
    monkeypatch.setattr(feature_importance, "train_if_needed", lambda _: {"status": "ok"})
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        1,
        "home",
        "away",
        None,
        0,
        0.6,
        *([None] * (len(FEATURE_COLUMNS) - 3)),
    )
    assert feature_importance.explain_prediction(conn, 1)["status"] == "ok"
    np.testing.assert_allclose(classifier.rows[0], [[np.nan, 0.0, 0.6]], equal_nan=True)


def test_dataset_restricts_semantics_and_preserves_nan_zero_false():
    from scripts.feature_schema import COMPATIBLE_SNAPSHOT_VERSIONS

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [
        ("2026-01-01", 0, False, float("inf"), *([None] * (len(FEATURE_COLUMNS) - 3)), 2)
    ]
    features, labels, dates = prematch_feature_dataset.load_settled_pre_kickoff_dataset(conn)
    query, params = cursor.execute.call_args.args
    assert "fs.feature_version IN %(feature_versions)s" in query
    assert params == {"feature_versions": COMPATIBLE_SNAPSHOT_VERSIONS}
    assert features.shape == (1, 55)
    assert features[0, 0] == features[0, 1] == 0
    assert np.isnan(features[0, 2:]).all()
    assert labels.tolist() == [2]
    assert dates == ["2026-01-01"]


def test_shap_missing_feature_is_null_and_strict_json_safe(monkeypatch):
    monkeypatch.setattr(feature_importance, "_trained_model", Classifier())
    monkeypatch.setattr(feature_importance, "_feature_names_cache", list(FEATURE_COLUMNS[:3]))
    monkeypatch.setattr(feature_importance, "_explainer_initialized", True)
    monkeypatch.setattr(feature_importance, "train_if_needed", lambda _: {"status": "ok"})
    monkeypatch.setattr(
        feature_importance,
        "_trained_explainer",
        lambda _: SimpleNamespace(
            values=np.array([[[0.1, 0.2, 0.3]] * 3]), base_values=np.array([[0.3, 0.3, 0.4]])
        ),
    )
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (
        1,
        "home",
        "away",
        None,
        0,
        0.6,
        *([None] * (len(FEATURE_COLUMNS) - 3)),
    )
    result = feature_importance.explain_prediction(conn, 1)
    values = {entry["feature"]: entry["feature_value"] for entry in result["shap_values"]}
    assert values[FEATURE_COLUMNS[0]] is None
    assert values[FEATURE_COLUMNS[1]] == 0
    assert json.loads(json.dumps(result, allow_nan=False))["status"] == "ok"


def test_legacy_signal_falls_back_without_committee_vote_or_artifact_load(monkeypatch):
    from scripts.jobs import run_model_prediction as prediction

    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [[(11, "h", 2.1), (12, "d", 3.2), (13, "a", 3.6)], []]
    monkeypatch.setattr(
        prediction, "_latest_feature_snapshot", lambda *_args, **_kwargs: snapshot()
    )
    monkeypatch.setattr(prediction, "store_derived_play_predictions", lambda *_args, **_kwargs: 0)
    store = Mock()
    vote = Mock()
    artifact = Mock(side_effect=AssertionError("legacy artifact must not load"))
    monkeypatch.setattr(prediction, "store_model_prediction", store)
    monkeypatch.setattr(prediction, "store_committee_vote", vote)
    monkeypatch.setattr(joblib, "load", artifact)
    legacy = parameters()
    legacy.pop("feature_schema_version")
    legacy.pop("feature_input_policy")
    result = prediction._predict_match_play_type(
        conn=conn,
        mid=101,
        home_team_name="home",
        away_team_name="away",
        play_type="spf",
        active_models={"logistic_shadow": 1},
        rho=-0.05,
        mle_rho=None,
        predict_time="2026-01-01T12:00:00",
        model_parameters={"logistic_shadow": legacy},
    )
    assert result == (3, 0)
    stored = [call.args[1] for call in store.call_args_list]
    assert len(stored) == 3
    assert all(row["model_probability"] == row["market_probability"] for row in stored)
    assert all(row["uncertainty_reason"]["model_independent"] is False for row in stored)
    vote.assert_not_called()
    artifact.assert_not_called()
