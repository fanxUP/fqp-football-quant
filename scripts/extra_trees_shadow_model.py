"""极端随机树赛前影子模型的训练与推理边界。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

MIN_TRAINING_MATCHES = 100
MIN_VALIDATION_MATCHES = 25


@dataclass(frozen=True)
class ExtraTreesShadowProfile:
    """已验证的极端随机树影子模型元数据；不包含业务决策状态。"""

    artifact_path: str
    feature_columns: tuple[str, ...]
    training_matches: int
    validation_matches: int
    validation_log_loss: float


def fit_temporal_holdout(
    rows: np.ndarray,
    labels: np.ndarray,
    feature_columns: tuple[str, ...],
) -> tuple[Any, ExtraTreesShadowProfile]:
    """Fit historical rows and evaluate exclusively against later matches."""
    if len(rows) != len(labels):
        raise ValueError("feature rows and labels must have equal length")
    validation_matches = max(MIN_VALIDATION_MATCHES, math.ceil(len(rows) * 0.2))
    training_matches = len(rows) - validation_matches
    if training_matches < MIN_TRAINING_MATCHES:
        raise ValueError("insufficient chronological samples for extra trees shadow training")

    from sklearn.ensemble import ExtraTreesClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import log_loss
    from sklearn.pipeline import Pipeline

    classifier = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "classifier",
                ExtraTreesClassifier(
                    n_estimators=300,
                    min_samples_leaf=4,
                    max_features="sqrt",
                    class_weight="balanced",
                    random_state=42,
                    n_jobs=1,
                ),
            ),
        ]
    )
    classifier.fit(rows[:training_matches], labels[:training_matches])
    probabilities = classifier.predict_proba(rows[training_matches:])
    validation_log_loss = float(
        log_loss(labels[training_matches:], probabilities, labels=[0, 1, 2])
    )
    return classifier, ExtraTreesShadowProfile(
        artifact_path="",
        feature_columns=feature_columns,
        training_matches=training_matches,
        validation_matches=validation_matches,
        validation_log_loss=validation_log_loss,
    )


def profile_from_parameters(parameters: dict[str, Any] | None) -> ExtraTreesShadowProfile | None:
    """Accept only complete, persisted shadow-validation profiles."""
    if not parameters or parameters.get("rollout_mode") != "shadow":
        return None
    try:
        profile = ExtraTreesShadowProfile(
            artifact_path=str(parameters["artifact_path"]),
            feature_columns=tuple(str(column) for column in parameters["feature_columns"]),
            training_matches=int(parameters["training_matches"]),
            validation_matches=int(parameters["validation_matches"]),
            validation_log_loss=float(parameters["validation_log_loss"]),
        )
    except (KeyError, TypeError, ValueError):
        return None
    if (
        not profile.artifact_path
        or not profile.feature_columns
        or profile.training_matches < MIN_TRAINING_MATCHES
        or profile.validation_matches < MIN_VALIDATION_MATCHES
        or not math.isfinite(profile.validation_log_loss)
        or profile.validation_log_loss <= 0
    ):
        return None
    return profile


def load_probabilities(
    parameters: dict[str, Any] | None,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Artifact errors simply suppress this optional shadow signal."""
    profile = profile_from_parameters(parameters)
    if profile is None or feature_snapshot is None:
        return None
    try:
        import joblib

        return probabilities_from_classifier(joblib.load(profile.artifact_path), profile, feature_snapshot)
    except (ImportError, OSError, ValueError):
        return None


def probabilities_from_classifier(
    classifier: Any,
    profile: ExtraTreesShadowProfile,
    feature_snapshot: dict[str, Any],
) -> dict[str, float] | None:
    """Map sklearn classes {0,1,2} to official 客胜/平局/主胜 option codes."""
    values: list[float] = []
    for column in profile.feature_columns:
        try:
            values.append(float(feature_snapshot[column]))
        except (KeyError, TypeError, ValueError):
            values.append(math.nan)
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
