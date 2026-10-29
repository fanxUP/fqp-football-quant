"""Explanation reads must not train or acquire a database connection unnecessarily."""

from unittest.mock import Mock

import pytest

from apps.backend.src.routers import analysis
from scripts import feature_importance


@pytest.fixture(autouse=True)
def isolated_artifact(monkeypatch, tmp_path):
    monkeypatch.setenv("FQP_FEATURE_MODEL_ARTIFACT_PATH", str(tmp_path / "explanation.json"))


@pytest.mark.parametrize(
    "url",
    [
        "/api/analysis/features/importance",
        "/api/analysis/features/model-info",
        "/api/analysis/explain/88",
    ],
)
def test_unready_get_never_trains_or_opens_database(client, monkeypatch, url):
    train = Mock(side_effect=AssertionError("GET attempted training"))
    database = Mock(side_effect=AssertionError("unready read attempted database"))
    monkeypatch.setattr(feature_importance, "train_if_needed", train)
    # Patch the old imported alias too, so the regression detects both entry paths.
    monkeypatch.setattr(analysis, "train_if_needed", train, raising=False)
    monkeypatch.setattr(analysis, "get_db", database)

    response = client.get(url)

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert "后台" in response.json()["error"]
    train.assert_not_called()
    database.assert_not_called()


def test_force_retrain_on_get_is_rejected_without_business_work(client, monkeypatch):
    train = Mock(side_effect=AssertionError("GET attempted training"))
    database = Mock(side_effect=AssertionError("GET attempted database"))
    monkeypatch.setattr(analysis, "train_if_needed", train, raising=False)
    monkeypatch.setattr(analysis, "get_db", database)

    response = client.get("/api/analysis/features/importance?force_retrain=true")

    assert response.status_code == 400
    assert "后台" in response.json()["detail"]
    train.assert_not_called()
    database.assert_not_called()


@pytest.mark.parametrize("method", ["gain", "permutation", "both"])
def test_ready_rankings_and_info_share_identity_without_native_loading(client, monkeypatch, method):
    rankings = [{"feature": "fixture", "label": "测试", "importance": 0.1}]
    state = {
        "artifact": {
            "sha256": "same-version",
            "info": {
                "n_samples": 120,
                "n_features": 1,
                "train_accuracy": 0.7,
                "trained_at": "2026-10-29T00:00:00+00:00",
            },
            "importance": {"gain": rankings, "permutation": rankings},
        },
        "error": "上次更新失败",
    }
    monkeypatch.setattr(feature_importance.explanation_artifact, "read_state", lambda: state)
    database = Mock(side_effect=AssertionError("GET attempted DB"))
    native_load = Mock(side_effect=AssertionError("metadata loaded native model"))
    monkeypatch.setattr(analysis, "get_db", database)
    monkeypatch.setattr(feature_importance.explanation_artifact, "load_classifier", native_load)

    response = client.get(f"/api/analysis/features/importance?method={method}")
    info = client.get("/api/analysis/features/model-info").json()

    assert response.status_code == 200
    assert response.json()["model_info"] == info
    assert info["artifact_id"] == "same-version"
    assert info["warning"] == "上次更新失败"
    assert response.json()["rankings"] == (
        {"gain": rankings, "permutation": rankings} if method == "both" else rankings
    )
    database.assert_not_called()
    native_load.assert_not_called()
