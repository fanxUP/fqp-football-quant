"""Atomic, validated artifacts for the existing analysis-only XGBoost model.

The API and scheduler already share .runtime (also in Docker Desktop).
Only the trainer writes here; readers never create directories or train models.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any

from scripts.feature_schema import (
    FEATURE_COLUMNS,
    FEATURE_INPUT_POLICY,
    FEATURE_SCHEMA_VERSION,
    valid_feature_columns,
)
from scripts.model_artifact_identity import canonical_json_bytes

_MAX_BYTES = 16 * 1024 * 1024
_MODEL_LOCK = RLock()
MIN_FEATURE_MODEL_MATCHES = 100


def artifact_path() -> Path:
    return Path(
        os.environ.get(
            "FQP_FEATURE_MODEL_ARTIFACT_PATH",
            str(Path(__file__).resolve().parents[1] / ".runtime/feature-explanation.json"),
        )
    )


@contextmanager
def training_lock() -> Iterator[bool]:
    """One trainer across processes; lock release also survives process exit."""
    path = artifact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _validate_artifact(artifact: dict[str, Any]) -> None:
    payload = {k: v for k, v in artifact.items() if k != "sha256"}
    if artifact.get("sha256") != hashlib.sha256(canonical_json_bytes(payload)).hexdigest():
        raise ValueError("explanation artifact digest mismatch")
    features = artifact.get("features")
    if not isinstance(features, list):
        raise ValueError("explanation features must be an ordered list")
    if (
        artifact.get("schema_version") != 1
        or artifact.get("kind") != "feature-explanation-xgboost"
        or artifact.get("feature_schema_version") != FEATURE_SCHEMA_VERSION
        or artifact.get("feature_input_policy") != FEATURE_INPUT_POLICY
        or not valid_feature_columns(features)
        or features != [f for f in FEATURE_COLUMNS if f in features]
    ):
        raise ValueError("explanation feature contract mismatch")
    info = artifact["info"]
    if (
        type(info["n_samples"]) is not int
        or info["n_samples"] < MIN_FEATURE_MODEL_MATCHES
        or info["n_features"] != len(features)
        or info["feature_count"] != len(features)
        or not 0 <= info["train_accuracy"] <= 1
        or set(info["class_distribution"]) != {"home_win", "draw", "away_win"}
        or any(type(n) is not int or n < 1 for n in info["class_distribution"].values())
        or sum(info["class_distribution"].values()) != info["n_samples"]
        or datetime.fromisoformat(info["trained_at"]).utcoffset() is None
    ):
        raise ValueError("explanation training metadata mismatch")
    for method in ("gain", "permutation"):
        rankings = artifact["importance"][method]
        if len(rankings) != len(features) or sorted(r["feature"] for r in rankings) != sorted(
            features
        ):
            raise ValueError("incomplete explanation importance")
        for row in rankings:
            if not isinstance(row["label"], str) or type(row["importance"]) not in (int, float):
                raise ValueError("invalid explanation ranking")
    if not base64.b64decode(artifact["model"], validate=True):
        raise ValueError("empty explanation classifier")


@lru_cache(maxsize=2)
def _read_cached(path: str, signature: tuple[int, int, int]) -> dict[str, Any]:
    with Path(path).open("rb") as handle:
        content = handle.read(_MAX_BYTES + 1)
    if len(content) > _MAX_BYTES:
        raise ValueError("explanation artifact too large")
    state = json.loads(content)
    if not isinstance(state, dict) or set(state) != {"artifact", "error"}:
        raise ValueError("invalid explanation state")
    if state.get("artifact") is not None:
        _validate_artifact(state["artifact"])
    if state.get("error") is not None and not isinstance(state["error"], str):
        raise ValueError("invalid explanation status")
    if state["artifact"] is None and not state["error"]:
        raise ValueError("unready explanation requires a reason")
    return state


def read_state() -> dict[str, Any]:
    """Metadata reads do not import XGBoost/SHAP or acquire a DB connection."""
    try:
        path = artifact_path()
        stat = path.stat()
        return _read_cached(str(path), (stat.st_mtime_ns, stat.st_size, stat.st_ino))
    except FileNotFoundError:
        return {"artifact": None, "error": "解释模型尚未就绪，等待后台训练任务生成结果"}
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        return {"artifact": None, "error": "解释模型工件不可用，等待后台重新训练"}


@lru_cache(maxsize=1)
def _load_classifier(content: str, features: tuple[str, ...]) -> Any:
    import numpy as np
    import xgboost as xgb

    from scripts.shadow_model_helpers import artifact_matches_features

    model = xgb.XGBClassifier(n_jobs=1)
    model.load_model(bytearray(base64.b64decode(content, validate=True)))
    if not artifact_matches_features(model, features) or not np.array_equal(
        model.classes_, [0, 1, 2]
    ):
        raise ValueError("explanation classifier width/classes mismatch")
    return model


def load_classifier(artifact: dict[str, Any]) -> Any:
    # lru_cache alone may execute a cache miss twice in concurrent requests.
    with _MODEL_LOCK:
        return _load_classifier(artifact["model"], tuple(artifact["features"]))


def make_artifact(
    model: Any, features: list[str], importance: dict[str, Any], info: dict[str, Any]
) -> dict[str, Any]:
    artifact = {
        "schema_version": 1,
        "kind": "feature-explanation-xgboost",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_input_policy": FEATURE_INPUT_POLICY,
        "features": features,
        "model": base64.b64encode(model.get_booster().save_raw(raw_format="ubj")).decode("ascii"),
        "importance": {method: importance[method] for method in ("permutation", "gain")},
        "info": {**info, "trained_at": datetime.now(UTC).isoformat()},
    }
    artifact["sha256"] = hashlib.sha256(canonical_json_bytes(artifact)).hexdigest()
    return artifact


def _write_state(state: dict[str, Any]) -> None:
    content = canonical_json_bytes(state)
    if len(content) > _MAX_BYTES:
        raise ValueError("explanation artifact too large")
    path = artifact_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".feature-explanation-", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def publish_artifact(artifact: dict[str, Any]) -> None:
    _validate_artifact(artifact)
    load_classifier(artifact)  # Verify native deserialization before replacing a valid result.
    _write_state({"artifact": artifact, "error": None})


def record_failure(message: str) -> None:
    """Keep the previous valid artifact and its original trained_at unchanged."""
    _write_state({"artifact": read_state()["artifact"], "error": message})
