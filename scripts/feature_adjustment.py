"""Conservative, explainable feature adjustments for Poisson goal rates.

The adjustment layer is intentionally bounded. It uses only pre-match fields
whose direction is explicit and keeps the market-derived goal rates as the
anchor. Every applied signal is returned for audit and later calibration.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

ADJUSTMENT_VERSION = "feature_rule_v1"
MIN_COMPLETENESS = 50.0
MAX_LOG_SHIFT = 0.15
MIN_GOAL_RATE = 0.2
MAX_GOAL_RATE = 4.5


@dataclass(frozen=True)
class GoalRateAdjustment:
    home_lambda: float
    away_lambda: float
    applied: bool
    home_log_shift: float
    total_goal_multiplier: float
    reasons: list[dict[str, float | str]]
    version: str = ADJUSTMENT_VERSION


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _signal(
    snapshot: dict[str, Any],
    name: str,
    coefficient: float,
    value_limit: float,
    reasons: list[dict[str, float | str]],
) -> float:
    raw_value = snapshot.get(name)
    if raw_value is None:
        return 0.0
    value = _clip(float(raw_value), -value_limit, value_limit)
    shift = value * coefficient
    reasons.append({"feature": name, "value": round(value, 4), "log_shift": round(shift, 6)})
    return shift


def adjust_goal_rates(
    home_lambda: float,
    away_lambda: float,
    snapshot: dict[str, Any] | None,
) -> GoalRateAdjustment:
    """Adjust market-derived goal rates with bounded pre-match feature signals."""
    if not snapshot or float(snapshot.get("data_completeness_score") or 0) < MIN_COMPLETENESS:
        return GoalRateAdjustment(home_lambda, away_lambda, False, 0.0, 1.0, [])

    reasons: list[dict[str, float | str]] = []
    home_shift = sum(
        (
            _signal(snapshot, "lineup_strength_diff", 0.0015, 100.0, reasons),
            _signal(snapshot, "absence_impact_diff", -0.0010, 100.0, reasons),
            _signal(snapshot, "rest_days_diff", 0.0100, 7.0, reasons),
            _signal(snapshot, "motivation_diff", 0.0008, 100.0, reasons),
            _signal(snapshot, "rotation_risk_diff", -0.0006, 100.0, reasons),
        )
    )
    home_shift = _clip(home_shift, -MAX_LOG_SHIFT, MAX_LOG_SHIFT)

    weather_value = snapshot.get("goal_expectation_weather_adjustment")
    weather_adjustment = _clip(float(weather_value or 0), -0.12, 0.05)
    total_goal_multiplier = 1.0 + weather_adjustment
    if weather_value is not None:
        reasons.append(
            {
                "feature": "goal_expectation_weather_adjustment",
                "value": round(float(weather_value), 6),
                "multiplier": round(total_goal_multiplier, 6),
            }
        )

    adjusted_home = _clip(
        home_lambda * math.exp(home_shift) * total_goal_multiplier,
        MIN_GOAL_RATE,
        MAX_GOAL_RATE,
    )
    adjusted_away = _clip(
        away_lambda * math.exp(-home_shift) * total_goal_multiplier,
        MIN_GOAL_RATE,
        MAX_GOAL_RATE,
    )
    applied = bool(reasons) and (
        abs(adjusted_home - home_lambda) > 1e-9 or abs(adjusted_away - away_lambda) > 1e-9
    )

    return GoalRateAdjustment(
        home_lambda=round(adjusted_home, 6),
        away_lambda=round(adjusted_away, 6),
        applied=applied,
        home_log_shift=round(home_shift, 6),
        total_goal_multiplier=round(total_goal_multiplier, 6),
        reasons=reasons,
    )
