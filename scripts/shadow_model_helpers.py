"""Shared loading, validation and official-option mapping for shadow models."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


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
    if profile is None or feature_snapshot is None:
        return None
    try:
        import joblib

        return probabilities_from_classifier(
            joblib.load(profile.artifact_path), profile, feature_snapshot
        )
    except ImportError, OSError, ValueError:
        return None
