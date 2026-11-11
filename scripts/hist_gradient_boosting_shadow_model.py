"""直方图梯度提升树赛前影子模型的训练与推理边界。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from scripts.shadow_model_helpers import (
    load_shadow_probabilities,
    map_official_probabilities,
    valid_shadow_profile,
)

MIN_TRAINING_MATCHES = 100
MIN_VALIDATION_MATCHES = 25


@dataclass(frozen=True)
class HistGradientBoostingShadowProfile:
    """已验证的直方图梯度提升影子模型元数据；不包含业务决策状态。"""

    artifact_path: str
    feature_columns: tuple[str, ...]
    training_matches: int
    validation_matches: int
    validation_log_loss: float


def fit_temporal_holdout(
    rows: np.ndarray,
    labels: np.ndarray,
    feature_columns: tuple[str, ...],
) -> tuple[Any, HistGradientBoostingShadowProfile]:
    """Fit historical rows and evaluate exclusively against later matches."""
    if len(rows) != len(labels):
        raise ValueError("feature rows and labels must have equal length")
    validation_matches = max(MIN_VALIDATION_MATCHES, math.ceil(len(rows) * 0.2))
    training_matches = len(rows) - validation_matches
    if training_matches < MIN_TRAINING_MATCHES:
        raise ValueError(
            "insufficient chronological samples for hist gradient boosting shadow training"
        )

    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import log_loss
    from sklearn.pipeline import Pipeline

    classifier = Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            (
                "classifier",
                HistGradientBoostingClassifier(
                    learning_rate=0.05,
                    max_iter=200,
                    max_leaf_nodes=15,
                    l2_regularization=1.0,
                    early_stopping=False,
                    random_state=42,
                ),
            ),
        ]
    )
    classifier.fit(rows[:training_matches], labels[:training_matches])
    probabilities = classifier.predict_proba(rows[training_matches:])
    validation_log_loss = float(
        log_loss(labels[training_matches:], probabilities, labels=[0, 1, 2])
    )
    return classifier, HistGradientBoostingShadowProfile(
        artifact_path="",
        feature_columns=feature_columns,
        training_matches=training_matches,
        validation_matches=validation_matches,
        validation_log_loss=validation_log_loss,
    )


def profile_from_parameters(
    parameters: dict[str, Any] | None,
) -> HistGradientBoostingShadowProfile | None:
    """Accept only complete, persisted shadow-validation profiles."""
    if not parameters or parameters.get("rollout_mode") != "shadow":
        return None
    try:
        profile = HistGradientBoostingShadowProfile(
            artifact_path=str(parameters["artifact_path"]),
            feature_columns=tuple(str(column) for column in parameters["feature_columns"]),
            training_matches=int(parameters["training_matches"]),
            validation_matches=int(parameters["validation_matches"]),
            validation_log_loss=float(parameters["validation_log_loss"]),
        )
    except KeyError, TypeError, ValueError:
        return None
    if not valid_shadow_profile(
        profile.artifact_path,
        profile.feature_columns,
        profile.training_matches,
        profile.validation_matches,
        profile.validation_log_loss,
        min_training_matches=MIN_TRAINING_MATCHES,
        min_validation_matches=MIN_VALIDATION_MATCHES,
    ):
        return None
    return profile


def load_probabilities(
    parameters: dict[str, Any] | None,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, float] | None:
    """Artifact errors simply suppress this optional shadow signal."""
    return load_shadow_probabilities(
        parameters,
        feature_snapshot,
        profile_from_parameters=profile_from_parameters,
        probabilities_from_classifier=probabilities_from_classifier,
    )


def probabilities_from_classifier(
    classifier: Any,
    profile: HistGradientBoostingShadowProfile,
    feature_snapshot: dict[str, Any],
) -> dict[str, float] | None:
    """Map sklearn classes {0,1,2} to official 客胜/平局/主胜 option codes."""
    values: list[float] = []
    for column in profile.feature_columns:
        try:
            values.append(float(feature_snapshot[column]))
        except KeyError, TypeError, ValueError:
            values.append(math.nan)
    probabilities = classifier.predict_proba([values])
    classes = getattr(classifier, "classes_", None)
    if classes is None or len(probabilities) != 1 or len(probabilities[0]) != len(classes):
        return None
    return map_official_probabilities(classes, probabilities[0])
