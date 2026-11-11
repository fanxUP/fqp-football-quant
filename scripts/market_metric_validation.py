"""Fail-closed validation for one complete official betting market."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from typing import Any

PROBABILITY_SUM_TOLERANCE = 0.005


def finite_number(value: Any) -> float | None:
    """Parse legacy/DB numbers without treating missing, boolean or NaN as data."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if isfinite(number) else None


def probability_value(value: Any) -> float | None:
    number = finite_number(value)
    return number if number is not None and 0 <= number <= 1 else None


def spf_probability_vector(values: Mapping[str, Any] | None) -> dict[str, float] | None:
    """Accept one complete SPF distribution; preserve original rounding."""
    if not isinstance(values, Mapping) or set(values) != {"3", "1", "0"}:
        return None
    parsed = {}
    for option, value in values.items():
        probability = probability_value(value)
        if probability is None:
            return None
        parsed[option] = probability
    if abs(sum(parsed.values()) - 1.0) > PROBABILITY_SUM_TOLERANCE:
        return None
    return parsed


class MarketMetricValidationError(ValueError):
    """Raised when probabilities, odds, or option evidence are inconsistent."""


@dataclass(frozen=True)
class OptionMetrics:
    break_even_probability: float
    market_edge: float
    breakeven_edge: float
    expected_value: float


def validate_market(
    *,
    model_probabilities: Mapping[str, float],
    market_probabilities: Mapping[str, float],
    odds_by_option: Mapping[str, float],
    snapshot_ids: Mapping[str, int],
    tolerance: float = PROBABILITY_SUM_TOLERANCE,
) -> dict[str, OptionMetrics]:
    """Validate and calculate metrics for the same market and evidence batch."""
    option_codes = set(model_probabilities)
    if not option_codes or any(
        set(values) != option_codes
        for values in (market_probabilities, odds_by_option, snapshot_ids)
    ):
        raise MarketMetricValidationError("模型、市场、赔率与快照结果代码不一致")
    if len(set(snapshot_ids.values())) != len(snapshot_ids):
        raise MarketMetricValidationError("不同结果错误绑定了同一个赔率快照")

    for label, probabilities in (
        ("模型", model_probabilities),
        ("市场", market_probabilities),
    ):
        for option_code, probability in probabilities.items():
            if not isfinite(probability) or probability < 0 or probability > 1:
                raise MarketMetricValidationError(f"{label}概率越界: {option_code}={probability}")
        probability_sum = sum(probabilities.values())
        if abs(probability_sum - 1.0) > tolerance:
            raise MarketMetricValidationError(f"{label}概率合计异常: {probability_sum:.6f}")

    metrics: dict[str, OptionMetrics] = {}
    for option_code in option_codes:
        odds = odds_by_option[option_code]
        if not isfinite(odds) or odds <= 1:
            raise MarketMetricValidationError(f"官方赔率非法: {option_code}={odds}")
        model_probability = model_probabilities[option_code]
        market_probability = market_probabilities[option_code]
        break_even_probability = 1.0 / odds
        metrics[option_code] = OptionMetrics(
            break_even_probability=break_even_probability,
            market_edge=model_probability - market_probability,
            breakeven_edge=model_probability - break_even_probability,
            expected_value=model_probability * odds - 1.0,
        )

    if abs(sum(metric.market_edge for metric in metrics.values())) > tolerance:
        raise MarketMetricValidationError("市场 Edge 合计异常")
    if all(metric.expected_value > 0 for metric in metrics.values()):
        raise MarketMetricValidationError("完整市场全部结果均为正 EV")
    return metrics
