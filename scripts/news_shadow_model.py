"""Bounded probability overlay used only by the news shadow experiment."""

from __future__ import annotations

import math
from collections.abc import Mapping

MAX_PROBABILITY_SHIFT = 0.03
SHADOW_VERSION = "news-shadow-v1"


def _normalize(probabilities: Mapping[str, float]) -> dict[str, float]:
    values = {option: max(1e-9, float(probabilities.get(option, 0))) for option in ("3", "1", "0")}
    total = sum(values.values())
    if total <= 0:
        raise ValueError("概率总和必须大于 0")
    return {option: value / total for option, value in values.items()}


def adjust_probabilities(
    baseline: Mapping[str, float],
    home_impact: float,
    away_impact: float,
) -> dict[str, float]:
    normalized = _normalize(baseline)
    relative_impact = max(-1.0, min(1.0, (float(home_impact) - float(away_impact)) / 2))
    shift = relative_impact * MAX_PROBABILITY_SHIFT
    adjusted = {
        "3": max(1e-9, normalized["3"] + shift),
        "1": normalized["1"],
        "0": max(1e-9, normalized["0"] - shift),
    }
    result = _normalize(adjusted)
    return {option: round(value, 9) for option, value in result.items()}


def score_prediction(probabilities: Mapping[str, float], actual: str) -> dict[str, float]:
    if actual not in {"3", "1", "0"}:
        raise ValueError("实际赛果必须是 3、1 或 0")
    normalized = _normalize(probabilities)
    brier = sum(
        (probability - (1.0 if option == actual else 0.0)) ** 2
        for option, probability in normalized.items()
    )
    return {
        "brier": round(brier, 9),
        "logLoss": round(-math.log(max(1e-15, normalized[actual])), 9),
    }
