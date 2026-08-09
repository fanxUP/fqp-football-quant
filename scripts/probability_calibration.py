"""Shadow-only multiclass probability calibration utilities.

The calibration layer is intentionally separate from model prediction writing.
It evaluates settled, pre-kickoff 1x2 distributions and produces profiles that
can be reviewed before any future decision-path promotion.
"""

from __future__ import annotations

import math
from typing import Any

OUTCOME_CODES = ("3", "1", "0")
_EPSILON = 1e-12


def _complete_distribution(probabilities: dict[str, float]) -> bool:
    try:
        values = [float(probabilities[code]) for code in OUTCOME_CODES]
    except (KeyError, TypeError, ValueError):
        return False
    return all(math.isfinite(value) and value > 0 for value in values)


def apply_temperature_scaling(probabilities: dict[str, float], temperature: float) -> dict[str, float]:
    """Return a normalized 1x2 distribution after temperature scaling.

    Temperature above one softens an overconfident distribution; below one
    sharpens it.  Invalid inputs fail closed instead of creating a partial
    output that could be mistaken for a usable prediction.
    """
    if not _complete_distribution(probabilities):
        raise ValueError("概率校准需要完整且为正的胜平负分布")
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("校准温度必须为正数")

    weights = {
        code: max(float(probabilities[code]), _EPSILON) ** (1.0 / temperature)
        for code in OUTCOME_CODES
    }
    total = sum(weights.values())
    return {code: weights[code] / total for code in OUTCOME_CODES}


def multiclass_log_loss(samples: list[tuple[dict[str, float], str]]) -> float:
    """Compute mean multiclass log loss for complete 1x2 distributions."""
    if not samples:
        raise ValueError("至少需要一条校准样本")
    losses = []
    for probabilities, actual in samples:
        if actual not in OUTCOME_CODES or not _complete_distribution(probabilities):
            raise ValueError("校准样本必须包含完整胜平负概率和实际赛果")
        total = sum(float(probabilities[code]) for code in OUTCOME_CODES)
        probability = max(float(probabilities[actual]) / total, _EPSILON)
        losses.append(-math.log(probability))
    return sum(losses) / len(losses)


def fit_temperature_scaling(
    samples: list[tuple[dict[str, float], str]],
    minimum_samples: int = 100,
) -> dict[str, Any] | None:
    """Fit a deterministic temperature on settled distributions.

    A small fixed grid keeps fitting dependency-free and fully reproducible.
    The output is for shadow comparison only and is never applied to current
    model predictions by this module.
    """
    if len(samples) < minimum_samples:
        return None
    try:
        baseline = multiclass_log_loss(samples)
    except ValueError:
        return None

    candidates = [round(0.50 + step * 0.05, 2) for step in range(61)]
    best_temperature = 1.0
    best_loss = baseline
    for temperature in candidates:
        calibrated = [
            (apply_temperature_scaling(probabilities, temperature), actual)
            for probabilities, actual in samples
        ]
        loss = multiclass_log_loss(calibrated)
        if loss < best_loss - 1e-12:
            best_temperature = temperature
            best_loss = loss

    return {
        "method_name": "temperature_scaling_v1",
        "temperature": best_temperature,
        "sample_count": len(samples),
        "log_loss_before": round(baseline, 6),
        "log_loss_after": round(best_loss, 6),
        "improved": best_loss < baseline - 1e-12,
    }
