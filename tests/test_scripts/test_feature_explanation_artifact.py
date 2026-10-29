"""Real native round trips, corruption, reader reload and trainer contention."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from scripts import feature_explanation_artifact as artifacts
from scripts import feature_importance
from scripts.feature_schema import FEATURE_COLUMNS
from scripts.model_artifact_identity import canonical_json_bytes


@pytest.fixture(autouse=True)
def isolated_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("FQP_FEATURE_MODEL_ARTIFACT_PATH", str(tmp_path / "explanation.json"))
    artifacts._read_cached.cache_clear()
    artifacts._load_classifier.cache_clear()


@pytest.fixture(scope="module")
def fitted_artifact():
    import xgboost as xgb

    features = list(FEATURE_COLUMNS[:3])
    inputs = np.random.default_rng(42).normal(size=(150, 3))
    inputs[0, 0] = np.nan
    labels = np.tile([0, 1, 2], 50)
    model = xgb.XGBClassifier(n_estimators=3, max_depth=2, n_jobs=1, random_state=42)
    model.fit(inputs, labels)
    rankings = [{"feature": f, "label": f, "importance": 0.1} for f in features]
    info = {
        "n_samples": 150,
        "n_features": 3,
        "feature_count": 3,
        "train_accuracy": 0.6,
        "class_distribution": {"home_win": 50, "draw": 50, "away_win": 50},
    }
    artifact = artifacts.make_artifact(
        model, features, {"gain": rankings, "permutation": rankings}, info
    )
    return artifact, inputs, model


def test_native_round_trip_preserves_probabilities_missing_policy_and_identity(fitted_artifact):
    artifact, inputs, trained = fitted_artifact
    artifacts.publish_artifact(artifact)
    restored = artifacts.load_classifier(artifacts.read_state()["artifact"])
    np.testing.assert_array_equal(trained.predict_proba(inputs), restored.predict_proba(inputs))
    assert feature_importance.get_feature_model_info()["artifact_id"] == artifact["sha256"]
    assert feature_importance.get_feature_model_info()["n_samples"] == 150


def test_metadata_and_rankings_never_deserialize_or_train(monkeypatch, fitted_artifact):
    artifacts.publish_artifact(fitted_artifact[0])

    def fail(*_a, **_k):
        pytest.fail("metadata tried native loading/training")

    monkeypatch.setattr(artifacts, "load_classifier", fail)
    monkeypatch.setattr(feature_importance, "train_if_needed", fail)
    result = feature_importance.get_feature_importance(method="both", top_n=2)
    assert len(result["rankings"]["gain"]) == 2
    assert result["model_info"]["artifact_id"] == fitted_artifact[0]["sha256"]


def test_readers_reload_atomic_publication_and_keep_failure_time(fitted_artifact):
    original = fitted_artifact[0]
    artifacts.publish_artifact(original)
    first = feature_importance.get_feature_model_info()
    artifacts.record_failure("训练数据不足（需要至少100场独立已结算比赛）")
    failed = feature_importance.get_feature_model_info()
    assert failed["artifact_id"] == first["artifact_id"]
    assert failed["trained_at"] == first["trained_at"]
    assert "100场" in failed["warning"]
    updated = copy.deepcopy(original)
    updated["info"]["trained_at"] = "2026-10-29T01:00:00+00:00"
    _resign(updated)
    artifacts.publish_artifact(updated)
    assert feature_importance.get_feature_model_info()["artifact_id"] == updated["sha256"]
    assert feature_importance.get_feature_model_info()["warning"] is None


def _resign(artifact):
    artifact["sha256"] = hashlib.sha256(
        canonical_json_bytes({k: v for k, v in artifact.items() if k != "sha256"})
    ).hexdigest()


@pytest.mark.parametrize("field", ["model", "features", "importance", "info"])
def test_corruption_is_not_exposed_as_valid_result(fitted_artifact, field):
    altered = copy.deepcopy(fitted_artifact[0])
    altered[field] = None
    artifacts.artifact_path().write_text(json.dumps({"artifact": altered, "error": None}))
    result = feature_importance.get_feature_model_info()
    assert result["status"] == "error"
    assert "不可用" in result["error"]


@pytest.mark.parametrize(
    "mutation", ["schema", "duplicate", "order", "counts", "importance", "width"]
)
def test_valid_digest_does_not_bypass_feature_and_model_contract(fitted_artifact, mutation):
    altered = copy.deepcopy(fitted_artifact[0])
    if mutation == "schema":
        altered["feature_schema_version"] = "obsolete"
    elif mutation == "duplicate":
        altered["features"][1] = altered["features"][0]
    elif mutation == "order":
        altered["features"] = list(reversed(altered["features"]))
    elif mutation == "counts":
        altered["info"]["n_samples"] = 99
    elif mutation == "importance":
        altered["importance"]["gain"] = []
    else:
        # Metadata is internally consistent, but the actual classifier has width 3.
        altered["features"] = altered["features"][:2]
        altered["info"]["n_features"] = altered["info"]["feature_count"] = 2
        for method in ("gain", "permutation"):
            altered["importance"][method] = altered["importance"][method][:2]
    _resign(altered)
    with pytest.raises(ValueError):
        artifacts.publish_artifact(altered)


def test_failed_atomic_replace_leaves_previous_complete_artifact(monkeypatch, fitted_artifact):
    artifacts.publish_artifact(fitted_artifact[0])
    before = artifacts.artifact_path().read_bytes()
    monkeypatch.setattr(
        artifacts.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("fixture"))
    )
    with pytest.raises(OSError):
        artifacts.record_failure("fixture failure")
    assert artifacts.artifact_path().read_bytes() == before
    assert not list(artifacts.artifact_path().parent.glob("*.tmp"))


def test_readers_never_observe_partial_state_during_publication(fitted_artifact):
    artifacts.publish_artifact(fitted_artifact[0])

    def read_many():
        return [feature_importance.get_feature_model_info()["artifact_id"] for _ in range(80)]

    with ThreadPoolExecutor(max_workers=3) as pool:
        readers = [pool.submit(read_many) for _ in range(2)]
        for _ in range(15):
            artifacts.record_failure("fixture update failed")
        assert all(v == fitted_artifact[0]["sha256"] for future in readers for v in future.result())


def test_separate_process_lock_prevents_loading_training_data():
    with artifacts.training_lock() as held:
        assert held
        process = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json; from scripts.feature_importance import train_if_needed; print(json.dumps(train_if_needed(object(), force=True)))",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    assert json.loads(process.stdout) == {"status": "skipped", "reason": "training_in_progress"}
    with artifacts.training_lock() as available:
        assert available


def test_new_process_reads_shared_artifact_without_training_or_native_imports(fitted_artifact):
    artifacts.publish_artifact(fitted_artifact[0])
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json,sys; from scripts.feature_importance import get_feature_importance; r=get_feature_importance(); assert 'xgboost' not in sys.modules; assert 'shap' not in sys.modules; print(json.dumps(r['model_info']))",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    info = json.loads(process.stdout)
    assert info["artifact_id"] == fitted_artifact[0]["sha256"]
    assert info["n_samples"] == 150


def test_read_only_missing_path_is_not_created(monkeypatch, tmp_path):
    missing = tmp_path / "not-created" / "explanation.json"
    monkeypatch.setenv("FQP_FEATURE_MODEL_ARTIFACT_PATH", str(missing))
    assert feature_importance.get_feature_importance()["status"] == "error"
    assert not missing.parent.exists()


@pytest.mark.parametrize("content", ["{}", "[]", "not json", '{"artifact":null,"error":null}'])
def test_invalid_status_is_an_explicit_unready_reason(content):
    artifacts.artifact_path().write_text(content)
    result = feature_importance.get_feature_model_info()
    assert result["status"] == "error"
    assert "不可用" in result["error"]


def test_training_failure_preserves_valid_artifact(monkeypatch, fitted_artifact):
    artifacts.publish_artifact(fitted_artifact[0])
    monkeypatch.setattr(feature_importance, "_load_training_data", lambda _c: None)
    result = feature_importance.train_if_needed(object(), force=True)
    assert result["reason"] == "insufficient_data"
    info = feature_importance.get_feature_model_info()
    assert info["status"] == "ok"
    assert info["artifact_id"] == fitted_artifact[0]["sha256"]
    assert "100场" in info["warning"]


def test_real_background_fit_is_persistent_and_does_not_build_shap(monkeypatch):
    inputs = np.random.default_rng(7).normal(size=(150, 3))
    labels = np.tile([0, 1, 2], 50)
    monkeypatch.setattr(
        feature_importance,
        "_load_training_data",
        lambda _c: (inputs, labels, list(range(150)), list(FEATURE_COLUMNS[:3])),
    )
    monkeypatch.setattr(
        feature_importance, "_build_shap_explainer", lambda *_a: pytest.fail("eager SHAP")
    )
    result = feature_importance.train_if_needed(object(), force=True)
    assert result["status"] == "ok"
    artifacts._read_cached.cache_clear()
    artifacts._load_classifier.cache_clear()
    rankings = feature_importance.get_feature_importance()
    assert len(rankings["rankings"]) == 3
    assert rankings["model_info"]["artifact_id"] == result["artifact_id"]
    model = artifacts.load_classifier(artifacts.read_state()["artifact"])
    assert model.predict_proba(inputs[:2]).shape == (2, 3)
