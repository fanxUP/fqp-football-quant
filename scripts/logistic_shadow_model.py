"""正则化逻辑回归赛前影子模型的推理边界。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

MIN_TRAINING_MATCHES = 100
MIN_VALIDATION_MATCHES = 25


@dataclass(frozen=True)
class LogisticShadowProfile:
    """已验证的逻辑回归影子模型元数据；不包含业务决策状态。"""

    artifact_path: str
    feature_columns: tuple[str, ...]
    training_matches: int
    validation_matches: int
    validation_log_loss: float


def fit_temporal_holdout(
    rows: np.ndarray,
    labels: np.ndarray,
    feature_columns: tuple[str, ...],
) -> tuple[Any, LogisticShadowProfile]:
    """Fit early matches and report loss exclusively on the most recent holdout."""
    if len(rows) != len(labels):
        raise ValueError("feature rows and labels must have equal length")
    validation_matches = max(MIN_VALIDATION_MATCHES, math.ceil(len(rows) * 0.2))
    training_matches = len(rows) - validation_matches
    if training_matches < MIN_TRAINING_MATCHES:
        raise ValueError("insufficient chronological samples for logistic shadow training")

    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler

    classifier = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    C=0.25,
                    class_weight="balanced",
                    max_iter=500,
                    random_state=42,
                ),
            ),
        ]
    )
    classifier.fit(rows[:training_matches], labels[:training_matches])
    validation_probabilities = classifier.predict_proba(rows[training_matches:])
    validation_log_loss = float(
        log_loss(labels[training_matches:], validation_probabilities, labels=[0, 1, 2])
    )
    return classifier, LogisticShadowProfile(
        artifact_path="",
        feature_columns=feature_columns,
        training_matches=training_matches,
        validation_matches=validation_matches,
        validation_log_loss=validation_log_loss,
    )


def profile_from_parameters(parameters: dict[str, Any] | None) -> LogisticShadowProfile | None:
    """Read a persisted profile only when its validation evidence is complete."""
    if not parameters or parameters.get("rollout_mode") != "shadow":
        return None
    try:
        artifact_path = str(parameters["artifact_path"])
        feature_columns = tuple(str(column) for column in parameters["feature_columns"])
        training_matches = int(parameters["training_matches"])
        validation_matches = int(parameters["validation_matches"])
        validation_log_loss = float(parameters["validation_log_loss"])
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not artifact_path
        or not feature_columns
        or training_matches < MIN_TRAINING_MATCHES
        or validation_matches < MIN_VALIDATION_MATCHES
        or not math.isfinite(validation_log_loss)
        or validation_log_loss <= 0
    ):
        return None
    return LogisticShadowProfile(
        artifact_path=artifact_path,
        feature_columns=feature_columns,
        training_matches=training_matches,
        validation_matches=validation_matches,
        validation_log_loss=validation_log_loss,
    )


def load_probabilities(
    parameters: dict[str, Any] | None,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Load lazily; artifact failures remove this signal rather than changing decisions."""
    profile = profile_from_parameters(parameters)
    if profile is None or feature_snapshot is None:
        return None
    try:
        import joblib

        classifier = joblib.load(profile.artifact_path)
        return probabilities_from_classifier(classifier, profile, feature_snapshot)
    except (ImportError, OSError, ValueError):
        return None


def probabilities_from_classifier(
    classifier: Any,
    profile: LogisticShadowProfile,
    feature_snapshot: dict[str, Any],
) -> dict[str, float] | None:
    """Map classifier classes {0,1,2} to 客胜/平局/主胜 official option codes."""
    values: list[float] = []
    for column in profile.feature_columns:
        value = feature_snapshot.get(column)
        try:
            numeric = float(value) if value is not None else math.nan
        except (TypeError, ValueError):
            numeric = math.nan
        values.append(numeric)

    probabilities = classifier.predict_proba([values])
    classes = getattr(classifier, "classes_", None)
    if classes is None or len(probabilities) != 1 or len(probabilities[0]) != len(classes):
        return None
    by_class = {
        int(class_code): float(probability)
        for class_code, probability in zip(classes, probabilities[0], strict=True)
    }
    result = {"0": by_class.get(0, 0.0), "1": by_class.get(1, 0.0), "3": by_class.get(2, 0.0)}
    total = sum(result.values())
    if not math.isfinite(total) or total <= 0 or any(value < 0 for value in result.values()):
        return None
    return {code: round(value / total, 8) for code, value in result.items()}
