"""Explicit markets and descriptive disagreement, without a calibration claim."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

# These are conservative source groups, not proof of statistical independence.
MODEL_FAMILIES = {
    "maher_poisson": "maher_goal_rates",
    "dixon_coles": "maher_goal_rates",
    "bivariate_poisson": "maher_goal_rates",
    "negative_binomial_shadow": "maher_goal_rates",
    "elo_rating": "historical_ratings",
    "glicko2_rating": "historical_ratings",
    "bayesian_form": "historical_outcomes",
    **{
        name: "snapshot_classifiers"
        for name in (
            "logistic_shadow",
            "xgboost_shadow",
            "random_forest_shadow",
            "extra_trees_shadow",
            "hist_gradient_boosting_shadow",
            "adaboost_shadow",
            "lda_shadow",
            "knn_shadow",
            "mlp_shadow",
            "naive_bayes_shadow",
            "svm_shadow",
        )
    },
}
MODEL_MARKETS = {
    "market_baseline": ("spf", "rqspf", "bf", "zjq", "bqc"),
    **{name: ("spf",) for name in MODEL_FAMILIES},
    "maher_poisson": ("spf", "rqspf", "bf", "zjq"),
    "dixon_coles": ("spf", "rqspf", "bf", "zjq"),
    "bivariate_poisson": ("spf", "rqspf"),
    "negative_binomial_shadow": ("spf", "rqspf"),
}


def supports_market(model: str, play_type: str, handicap: float | None = None) -> bool:
    if play_type not in MODEL_MARKETS.get(model, ()):
        return False
    if play_type == "rqspf" and model != "market_baseline":
        return handicap is not None and math.isfinite(handicap) and handicap.is_integer()
    return True


def disagreement_diagnostic(
    probabilities: dict[str, dict[str, float]],
    active_models: dict[str, int],
    independence: dict[str, bool],
    rollout_modes: dict[str, str],
    validated_models: set[str],
    option: str,
) -> dict[str, Any]:
    """Equal weight per eligible family; fewer than two families means unknown."""
    families: dict[str, list[float]] = {}
    models = []
    weights = committee_weights(active_models, independence, rollout_modes, validated_models)
    for model in weights:
        distribution = probabilities.get(model, {})
        family = MODEL_FAMILIES.get(model)
        value = distribution.get(option)
        if family is None or value is None or not math.isfinite(value) or not 0 <= value <= 1:
            continue
        families.setdefault(family, []).append(value)
        models.append(model)
    values = [sum(v) / len(v) for v in families.values()]
    std = None
    if len(values) >= 2:
        mean = sum(values) / len(values)
        std = round((sum((v - mean) ** 2 for v in values) / len(values)) ** 0.5, 6)
    return {
        "kind": "family_disagreement_not_confidence",
        "model_std": std,
        "family_count": len(families),
        "families": sorted(families),
        "models": sorted(models),
        "status": "measured" if std is not None else "insufficient_families",
        "calibration": "not_available",
    }


def committee_weights(
    active_models: dict[str, int],
    independence: dict[str, bool],
    rollout_modes: dict[str, str],
    validated_models: set[str],
) -> dict[str, float]:
    """Keep model-specific rows but cap each eligible source family's total at one."""
    names = [
        name
        for name in validated_models
        if name in active_models
        and name in MODEL_FAMILIES
        and independence.get(name, False)
        and rollout_modes.get(name, "live") == "live"
    ]
    counts = Counter(MODEL_FAMILIES[name] for name in names)
    return {name: 1.0 / counts[MODEL_FAMILIES[name]] for name in sorted(names)}
