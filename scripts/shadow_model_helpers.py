"""Shared loading, validation and official-option mapping for shadow models."""

from __future__ import annotations

import io
import math
import pickle
from collections.abc import Callable
from numbers import Integral
from pathlib import Path
from typing import Any

from scripts.feature_schema import (
    FEATURE_INPUT_POLICY,
    SNAPSHOT_VERSIONS_BY_SCHEMA,
    numeric_feature_value,
    valid_feature_columns,
)
from scripts.model_artifact_identity import verify_file_artifact


def load_shadow_artifact(
    path: str,
    parameters: dict[str, Any],
    *,
    artifact_format: str = "joblib",
) -> Any:
    """Load exactly the verified bytes; retain legacy profiles without inventing hashes."""
    verified = "artifact_sha256" in parameters or "artifact_size_bytes" in parameters
    content = None
    if verified:
        content = Path(path).read_bytes()
        verify_file_artifact(
            content,
            sha256=parameters.get("artifact_sha256"),
            size_bytes=parameters.get("artifact_size_bytes"),
        )
    if artifact_format == "xgboost_json":
        import xgboost as xgb

        classifier = xgb.XGBClassifier()
        classifier.load_model(bytearray(content) if content is not None else path)
        return classifier
    if artifact_format != "joblib":
        raise ValueError("unsupported shadow artifact format")
    import joblib

    return joblib.load(io.BytesIO(content) if content is not None else path)


def prepare_shadow_input(
    parameters: dict[str, Any] | None,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Do not infer compatibility for old artifacts or changed snapshot semantics."""
    if (
        not parameters
        or feature_snapshot is None
        or parameters.get("feature_input_policy") != FEATURE_INPUT_POLICY
        or not valid_feature_columns(parameters.get("feature_columns"))
        or feature_snapshot.get("feature_version")
        not in SNAPSHOT_VERSIONS_BY_SCHEMA.get(str(parameters.get("feature_schema_version")), ())
    ):
        return None
    return {
        column: numeric_feature_value(feature_snapshot.get(column))
        for column in parameters["feature_columns"]
    }


def artifact_matches_features(classifier: Any, feature_columns: tuple[str, ...]) -> bool:
    """Check fitted width, and fitted ordered names when the artifact records them."""
    try:
        width = getattr(classifier, "n_features_in_", None)
        if not isinstance(width, Integral) or width != len(feature_columns):
            return False
        names = getattr(classifier, "feature_names_in_", None)
        return names is None or tuple(names) == feature_columns
    except AttributeError, TypeError, ValueError:
        return False


def valid_shadow_profile(
    artifact_path: str,
    feature_columns: tuple[str, ...],
    training_matches: int,
    validation_matches: int,
    validation_log_loss: float,
    *,
    min_training_matches: int,
    min_validation_matches: int,
) -> bool:
    return not (
        not artifact_path
        or not feature_columns
        or training_matches < min_training_matches
        or validation_matches < min_validation_matches
        or not math.isfinite(validation_log_loss)
        or validation_log_loss <= 0
    )


def map_official_probabilities(classes: Any, probabilities: Any) -> dict[str, float] | None:
    by_class = {
        int(class_code): float(probability)
        for class_code, probability in zip(classes, probabilities, strict=True)
    }
    result = {"0": by_class.get(0, 0.0), "1": by_class.get(1, 0.0), "3": by_class.get(2, 0.0)}
    total = sum(result.values())
    if not math.isfinite(total) or total <= 0 or any(value < 0 for value in result.values()):
        return None
    return {code: round(value / total, 8) for code, value in result.items()}


def load_shadow_probabilities(
    parameters: dict[str, Any] | None,
    feature_snapshot: dict[str, Any] | None,
    *,
    profile_from_parameters: Callable[[dict[str, Any] | None], Any],
    probabilities_from_classifier: Callable[[Any, Any, dict[str, Any]], dict[str, float] | None],
) -> dict[str, float] | None:
    """Load optional joblib signals with the existing validation/error boundary."""
    profile = profile_from_parameters(parameters)
    model_input = prepare_shadow_input(parameters, feature_snapshot)
    if profile is None or model_input is None:
        return None
    try:
        classifier = load_shadow_artifact(profile.artifact_path, parameters or {})
        if not artifact_matches_features(classifier, profile.feature_columns):
            return None
        return probabilities_from_classifier(classifier, profile, model_input)
    except ImportError, OSError, ValueError, TypeError, EOFError, pickle.UnpicklingError:
        return None
