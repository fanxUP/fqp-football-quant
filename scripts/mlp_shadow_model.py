"""MLP 赛前影子模型；训练和推理只提供评估信号。"""
# ruff: noqa: E701, E702
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

MIN_TRAINING_MATCHES, MIN_VALIDATION_MATCHES = 100, 25


@dataclass(frozen=True)
class MlpShadowProfile:
    artifact_path: str
    feature_columns: tuple[str, ...]
    training_matches: int
    validation_matches: int
    validation_log_loss: float


def fit_temporal_holdout(rows: np.ndarray, labels: np.ndarray, feature_columns: tuple[str, ...]) -> tuple[Any, MlpShadowProfile]:
    if len(rows) != len(labels): raise ValueError('feature rows and labels must have equal length')
    validation_matches = max(MIN_VALIDATION_MATCHES, math.ceil(len(rows) * .2))
    training_matches = len(rows) - validation_matches
    if training_matches < MIN_TRAINING_MATCHES: raise ValueError('insufficient chronological samples for MLP shadow training')
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import log_loss
    from sklearn.neural_network import MLPClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    classifier = Pipeline([('imputer', SimpleImputer(strategy='median', keep_empty_features=True)), ('scaler', StandardScaler()), ('classifier', MLPClassifier(hidden_layer_sizes=(24, 12), alpha=.03, early_stopping=True, max_iter=300, random_state=42))])
    classifier.fit(rows[:training_matches], labels[:training_matches])
    loss = float(log_loss(labels[training_matches:], classifier.predict_proba(rows[training_matches:]), labels=[0, 1, 2]))
    return classifier, MlpShadowProfile('', feature_columns, training_matches, validation_matches, loss)


def profile_from_parameters(parameters: dict[str, Any] | None) -> MlpShadowProfile | None:
    if not parameters or parameters.get('rollout_mode') != 'shadow': return None
    try: profile = MlpShadowProfile(str(parameters['artifact_path']), tuple(map(str, parameters['feature_columns'])), int(parameters['training_matches']), int(parameters['validation_matches']), float(parameters['validation_log_loss']))
    except (KeyError, TypeError, ValueError): return None
    if not profile.artifact_path or not profile.feature_columns or profile.training_matches < MIN_TRAINING_MATCHES or profile.validation_matches < MIN_VALIDATION_MATCHES or not math.isfinite(profile.validation_log_loss) or profile.validation_log_loss <= 0: return None
    return profile


def probabilities_from_classifier(classifier: Any, profile: MlpShadowProfile, feature_snapshot: dict[str, Any]) -> dict[str, float] | None:
    values = [float(feature_snapshot.get(column, math.nan)) for column in profile.feature_columns]
    probabilities, classes = classifier.predict_proba([values]), getattr(classifier, 'classes_', None)
    if classes is None or len(probabilities) != 1 or len(probabilities[0]) != len(classes): return None
    mapped = {int(kind): float(value) for kind, value in zip(classes, probabilities[0], strict=True)}
    result = {'0': mapped.get(0, 0.), '1': mapped.get(1, 0.), '3': mapped.get(2, 0.)}
    total = sum(result.values())
    if not math.isfinite(total) or total <= 0 or any(value < 0 for value in result.values()): return None
    return {code: round(value / total, 8) for code, value in result.items()}


def load_probabilities(parameters: dict[str, Any] | None, feature_snapshot: dict[str, Any] | None) -> dict[str, float] | None:
    profile = profile_from_parameters(parameters)
    if profile is None or feature_snapshot is None: return None
    try:
        import joblib
        return probabilities_from_classifier(joblib.load(profile.artifact_path), profile, feature_snapshot)
    except (ImportError, OSError, ValueError): return None
