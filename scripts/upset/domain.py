"""Pure domain logic for official-market upset detection."""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from scripts.odds_conversion import normalize_probabilities, overround
from scripts.result_codes import normalize_result


class IncompleteMarketError(ValueError):
    """Raised when one market cannot support an objective upset calculation."""


MINIMUM_OPTION_COUNTS = {
    "spf": 3,
    "rqspf": 3,
    "zjq": 8,
    "bqc": 9,
    "bf": 31,
}


@dataclass(frozen=True)
class UpsetRule:
    """Versioned thresholds used to classify one actual market outcome."""

    version: str
    extreme_max: float
    major_max: float
    general_max: float
    mild_max: float
    favourite_min: float
    play_thresholds: Mapping[str, tuple[float, float, float, float]] = field(
        default_factory=dict
    )

    @classmethod
    def default(cls) -> UpsetRule:
        return cls(
            version="upset-v1",
            extreme_max=0.15,
            major_max=0.22,
            general_max=0.30,
            mild_max=0.38,
            favourite_min=0.55,
            play_thresholds={
                "zjq": (0.04, 0.06, 0.09, 0.12),
                "bqc": (0.025, 0.04, 0.06, 0.08),
                "bf": (0.005, 0.01, 0.02, 0.03),
            },
        )

    def classify(self, probability: float, play_type: str = "spf") -> str | None:
        thresholds = self.play_thresholds.get(
            play_type,
            (self.extreme_max, self.major_max, self.general_max, self.mild_max),
        )
        extreme_max, major_max, general_max, mild_max = thresholds
        if probability < extreme_max:
            return "S"
        if probability < major_max:
            return "A"
        if probability < general_max:
            return "B"
        if probability < mild_max:
            return "C"
        return None


@dataclass(frozen=True)
class MarketSignal:
    """Objective calculation result for one official market."""

    play_type: str
    actual_option: str
    actual_probability: float
    surprise_bits: float
    upset_level: str | None
    market_favourite_option: str
    market_favourite_probability: float
    favourite_failed: bool
    market_probabilities: dict[str, float]
    market_overround: float
    rule_version: str


def resolve_actual_option(
    play_type: str,
    actual_result: object,
    available_options: Collection[str],
) -> str | None:
    """Map official/legacy result values to an option present in the market."""
    normalized = normalize_result(play_type, actual_result)
    if normalized is None:
        return None

    options = set(available_options)
    if normalized in options:
        return normalized

    if play_type != "bf" or ":" not in normalized:
        return None

    home_text, away_text = normalized.split(":", 1)
    try:
        home_goals = int(home_text)
        away_goals = int(away_text)
    except ValueError:
        return None

    if home_goals > away_goals:
        bucket = "other_h"
    elif home_goals == away_goals:
        bucket = "other_d"
    else:
        bucket = "other_a"
    return bucket if bucket in options else None


def _validate_market(play_type: str, odds_by_option: Mapping[str, float]) -> None:
    minimum = MINIMUM_OPTION_COUNTS.get(play_type)
    if minimum is None:
        raise IncompleteMarketError(f"不支持的玩法: {play_type}")
    if len(odds_by_option) < minimum:
        raise IncompleteMarketError(
            f"{play_type} 市场不完整，至少需要 {minimum} 个选项，当前 {len(odds_by_option)} 个"
        )
    invalid = {code: odds for code, odds in odds_by_option.items() if odds <= 1}
    if invalid:
        raise IncompleteMarketError(f"{play_type} 存在非法赔率: {invalid}")


def calculate_market_signal(
    *,
    play_type: str,
    odds_by_option: Mapping[str, float],
    actual_result: object,
    rule: UpsetRule,
) -> MarketSignal:
    """Calculate a reproducible upset signal from one complete market snapshot."""
    _validate_market(play_type, odds_by_option)
    actual_option = resolve_actual_option(play_type, actual_result, odds_by_option)
    if actual_option is None:
        raise IncompleteMarketError(f"{play_type} 实际赛果无法映射到官方选项")

    market_probabilities = normalize_probabilities(dict(odds_by_option))
    actual_probability = market_probabilities[actual_option]
    favourite_option, favourite_probability = max(
        market_probabilities.items(), key=lambda item: item[1]
    )

    return MarketSignal(
        play_type=play_type,
        actual_option=actual_option,
        actual_probability=actual_probability,
        surprise_bits=-math.log2(actual_probability),
        upset_level=rule.classify(actual_probability, play_type),
        market_favourite_option=favourite_option,
        market_favourite_probability=favourite_probability,
        favourite_failed=(
            favourite_probability >= rule.favourite_min and favourite_option != actual_option
        ),
        market_probabilities=market_probabilities,
        market_overround=overround(dict(odds_by_option)),
        rule_version=rule.version,
    )
