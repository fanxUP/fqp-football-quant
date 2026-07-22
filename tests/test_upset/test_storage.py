from __future__ import annotations

from datetime import datetime

from scripts.upset.detector import MarketDetection
from scripts.upset.domain import MarketSignal
from scripts.upset.storage import event_type, rule_from_thresholds, select_primary_detection


def _detection(probability: float, level: str | None, favourite_failed: bool) -> MarketDetection:
    signal = MarketSignal(
        play_type="spf",
        actual_option="0",
        actual_probability=probability,
        surprise_bits=3.0,
        upset_level=level,
        market_favourite_option="3",
        market_favourite_probability=0.60,
        favourite_failed=favourite_failed,
        market_probabilities={"3": 0.60, "1": 0.25, "0": 0.15},
        market_overround=0.08,
        rule_version="upset-v1",
    )
    return MarketDetection(
        play_type="spf",
        handicap=None,
        opening_snapshot_time=datetime(2026, 7, 20, 9),
        closing_snapshot_time=datetime(2026, 7, 20, 12),
        opening_odds={"3": 1.5, "1": 3.8, "0": 6.5},
        closing_odds={"3": 1.6, "1": 3.7, "0": 5.8},
        signal=signal,
        actual_odds_change_rate=-0.1,
    )


def test_rule_thresholds_are_loaded_from_database_version():
    rule = rule_from_thresholds(
        "custom-v2",
        {
            "S": 0.10,
            "A": 0.20,
            "B": 0.27,
            "C": 0.35,
            "favourite_min": 0.58,
            "by_play": {"bf": {"S": 0.01, "A": 0.02, "B": 0.04, "C": 0.06}},
        },
    )

    assert rule.version == "custom-v2"
    assert rule.classify(0.11) == "A"
    assert rule.classify(0.03, "bf") == "B"
    assert rule.favourite_min == 0.58


def test_primary_detection_is_the_least_likely_actual_result():
    primary = select_primary_detection([_detection(0.24, "B", False), _detection(0.12, "S", True)])

    assert primary.signal.actual_probability == 0.12


def test_event_type_keeps_odds_and_favourite_failures_distinct():
    assert event_type(_detection(0.12, "S", True)) == "odds_and_favourite"
    assert event_type(_detection(0.24, "B", False)) == "odds_upset"
    assert event_type(_detection(0.40, None, True)) == "favourite_failed"
