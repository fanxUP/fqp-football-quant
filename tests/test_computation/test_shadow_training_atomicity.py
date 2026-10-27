"""Immutable shadow artifact publication and verified inference, without external I/O."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import joblib
import numpy as np
import pytest
from sklearn.tree import DecisionTreeClassifier

from scripts import shadow_training
from scripts.feature_schema import CURRENT_SNAPSHOT_VERSION, FEATURE_SCHEMA_VERSION
from scripts.logistic_shadow_model import load_probabilities
from scripts.model_prediction_run_identity import build_model_artifact_identity

COLUMNS = ("home_lineup_confirmed", "home_team_market_value", "rest_days_diff")


def fitted():
    rows = np.arange(450).reshape(150, 3) % 7
    classifier = DecisionTreeClassifier(max_depth=2, random_state=42).fit(rows, np.arange(150) % 3)
    profile = SimpleNamespace(
        feature_columns=COLUMNS,
        training_matches=120,
        validation_matches=30,
        validation_log_loss=1.0,
    )
    return classifier, profile


def train(directory, conn=None, **overrides):
    classifier, profile = fitted()
    return shadow_training.train_shadow_with_connection(
        conn if conn is not None else Mock(autocommit=False),
        **(
            dict(
                load_dataset=lambda _: (
                    np.ones((150, 3)),
                    np.arange(150) % 3,
                    ["2026-01-01", "2026-02-01"],
                ),
                fit_model=lambda *_: (classifier, profile),
                feature_columns=COLUMNS,
                resolve_artifact=lambda: directory / "model.joblib",
                artifact_relative_path="model.joblib",
                model_name="logistic_shadow",
                missing_message="missing shadow model",
                store_profile=Mock(),
            )
            | overrides
        ),
    )


def snapshot():
    return {"feature_version": CURRENT_SNAPSHOT_VERSION, **dict.fromkeys(COLUMNS, 1)}


def saved_parameters(path):
    return {
        "rollout_mode": "shadow",
        "artifact_path": str(path),
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "artifact_size_bytes": path.stat().st_size,
        "feature_columns": list(COLUMNS),
        "training_matches": 120,
        "validation_matches": 30,
        "validation_log_loss": 1.0,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_input_policy": "snapshot-columns/v1",
    }


def test_new_training_retains_old_file_and_publishes_unique_loadable_versions(tmp_path):
    old = tmp_path / "model.joblib"
    old.write_bytes(b"legacy-file-must-not-change")
    store = Mock()
    for _ in range(2):
        assert train(tmp_path, store_profile=store)["status"] == "ok"
    records = [call.args[1] for call in store.call_args_list]
    assert old.read_bytes() == b"legacy-file-must-not-change"
    assert len({p["artifact_path"] for p in records}) == 2
    assert len({p["artifact_version"] for p in records}) == 2
    for params in records:
        path = tmp_path / params["artifact_path"]
        assert path != old
        assert params["artifact_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert params["artifact_size_bytes"] == path.stat().st_size
        assert load_probabilities(params | {"artifact_path": str(path)}, snapshot()) is not None
    assert not list(tmp_path.glob("*.tmp*"))


def test_metadata_failure_retains_old_file_and_an_unreferenced_new_file(tmp_path):
    old = tmp_path / "model.joblib"
    old.write_bytes(b"previous-artifact")
    conn = Mock(autocommit=False)
    store = Mock(side_effect=RuntimeError("database unavailable"))
    with pytest.raises(RuntimeError, match="database unavailable"):
        train(tmp_path, conn, store_profile=store)
    assert old.read_bytes() == b"previous-artifact"
    path = tmp_path / store.call_args.args[1]["artifact_path"]
    assert path != old and path.is_file()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


@pytest.mark.parametrize("failure", ["save", "unloadable", "features", "interrupted"])
def test_failed_artifact_never_reaches_activation(tmp_path, failure):
    old = tmp_path / "model.joblib"
    old.write_bytes(b"previous-artifact")
    store = Mock()

    def save(classifier, path):
        if failure == "save":
            path.write_bytes(b"partial")
            raise OSError("disk failure")
        if failure == "interrupted":
            raise KeyboardInterrupt()
        if failure == "unloadable":
            return path.write_bytes(b"unloadable")
        classifier.n_features_in_ = 99
        return joblib.dump(classifier, path)

    with pytest.raises((Exception, KeyboardInterrupt)):
        train(tmp_path, store_profile=store, save_artifact=save)
    store.assert_not_called()
    assert old.read_bytes() == b"previous-artifact"
    assert list(tmp_path.iterdir()) == [old]


@pytest.mark.parametrize("field,value", [("artifact_sha256", "a" * 64), ("artifact_size_bytes", 1)])
def test_inference_and_prediction_identity_reject_mismatched_saved_digest(tmp_path, field, value):
    path = tmp_path / "model.joblib"
    joblib.dump(fitted()[0], path)
    parameters = saved_parameters(path) | {field: value}
    assert load_probabilities(parameters, snapshot()) is None
    identity = build_model_artifact_identity(
        12, "logistic_shadow", parameters, artifact_root=tmp_path
    )
    assert identity["provenance_status"] == "incomplete"
    assert identity["reason"] == "artifact_digest_mismatch"


def test_modified_file_is_rejected_before_deserializing(tmp_path, monkeypatch):
    path = tmp_path / "model.joblib"
    joblib.dump(fitted()[0], path)
    parameters = saved_parameters(path)
    path.write_bytes(b"changed")
    load = Mock(side_effect=AssertionError("must not deserialize changed bytes"))
    monkeypatch.setattr(joblib, "load", load)
    assert load_probabilities(parameters, snapshot()) is None
    load.assert_not_called()


def test_training_rejects_autocommit_before_loading_or_writing(tmp_path):
    dataset = Mock()
    with pytest.raises(ValueError, match="autocommit"):
        train(tmp_path, Mock(autocommit=True), load_dataset=dataset)
    dataset.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_filename_collision_fails_without_overwriting_or_activating(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow_training, "uuid4", lambda: SimpleNamespace(hex="1" * 32))
    store = Mock()
    train(tmp_path, store_profile=store)
    path = tmp_path / store.call_args.args[1]["artifact_path"]
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        train(tmp_path, store_profile=store)
    assert path.read_bytes() == original
    assert store.call_count == 1
    assert list(tmp_path.iterdir()) == [path]


def test_xgboost_job_saves_and_loads_verified_json(tmp_path, monkeypatch):
    import xgboost as xgb

    from scripts.jobs import train_xgboost_shadow as job
    from scripts.xgboost_shadow_model import load_probabilities as load_xgboost

    rows = np.arange(450).reshape(150, 3) % 7
    classifier = xgb.XGBClassifier(n_estimators=2, max_depth=2, n_jobs=1).fit(
        rows, np.arange(150) % 3
    )
    profile = fitted()[1]
    store = Mock()
    monkeypatch.setattr(job, "FEATURE_COLUMNS", COLUMNS)
    monkeypatch.setattr(job, "_artifact_path", lambda: tmp_path / "model.json")
    monkeypatch.setattr(job, "ARTIFACT_RELATIVE_PATH", "model.json")
    monkeypatch.setattr(job, "fit_temporal_holdout", lambda *_: (classifier, profile))
    monkeypatch.setattr(
        job,
        "load_training_dataset",
        lambda _: (rows, np.arange(150) % 3, ["2026-01-01", "2026-02-01"]),
    )
    monkeypatch.setattr(job, "_store_profile", store)
    assert job._run_with_connection(Mock(autocommit=False))["status"] == "ok"
    parameters = store.call_args.args[1]
    path = tmp_path / parameters["artifact_path"]
    parameters["artifact_path"] = str(path)
    direct = classifier.predict_proba([[1, 1, 1]])[0]
    assert load_xgboost(parameters, snapshot()) == {
        code: round(float(probability), 8)
        for code, probability in zip(("0", "1", "3"), direct, strict=True)
    }
    assert (
        build_model_artifact_identity(12, "xgboost_shadow", parameters, artifact_root=tmp_path)[
            "provenance_status"
        ]
        == "complete"
    )
    parameters["artifact_sha256"] = "a" * 64
    assert load_xgboost(parameters, snapshot()) is None
