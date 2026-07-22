"""Build complete official market groups and orchestrate upset detection."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scripts.upset.domain import (
    MINIMUM_OPTION_COUNTS,
    IncompleteMarketError,
    MarketSignal,
    UpsetRule,
    calculate_market_signal,
)


@dataclass(frozen=True)
class MarketDetection:
    """Opening/closing context plus the objective closing-market signal."""

    play_type: str
    handicap: float | None
    opening_snapshot_time: datetime
    closing_snapshot_time: datetime
    opening_odds: dict[str, float]
    closing_odds: dict[str, float]
    signal: MarketSignal
    actual_odds_change_rate: float | None


def canonical_odds_option(play_type: str, option_code: object) -> str:
    """Normalize official h/d/a odds codes to canonical 3/1/0 codes."""
    raw = str(option_code).strip()
    if play_type in {"spf", "rqspf"}:
        return {"h": "3", "H": "3", "d": "1", "D": "1", "a": "0", "A": "0"}.get(
            raw, raw
        )
    return raw


def _odds_change(opening: float | None, closing: float | None) -> float | None:
    if opening is None or closing is None or opening <= 0:
        return None
    return (closing - opening) / opening


def build_market_detections(
    *,
    odds_rows: Iterable[tuple[Any, ...]],
    result_by_play: Mapping[str, object],
    rule: UpsetRule,
) -> list[MarketDetection]:
    """Select first/last complete snapshots for every play/handicap market."""
    grouped: dict[
        tuple[str, float | None, datetime],
        dict[str, tuple[int, float]],
    ] = defaultdict(dict)

    for snapshot_id, snapshot_time, play_type, option_code, sp_value, handicap in odds_rows:
        play = str(play_type)
        if play not in MINIMUM_OPTION_COUNTS or not isinstance(snapshot_time, datetime):
            continue
        line = float(handicap) if handicap is not None else None
        option = canonical_odds_option(play, option_code)
        key = (play, line, snapshot_time)
        previous = grouped[key].get(option)
        if previous is None or int(snapshot_id) > previous[0]:
            grouped[key][option] = (int(snapshot_id), float(sp_value))

    complete: dict[tuple[str, float | None], list[tuple[datetime, dict[str, float]]]] = (
        defaultdict(list)
    )
    for (play_type, handicap, snapshot_time), option_rows in grouped.items():
        if len(option_rows) < MINIMUM_OPTION_COUNTS[play_type]:
            continue
        odds = {option: value for option, (_snapshot_id, value) in option_rows.items()}
        complete[(play_type, handicap)].append((snapshot_time, odds))

    detections: list[MarketDetection] = []
    for (play_type, handicap), snapshots in complete.items():
        actual_result = result_by_play.get(play_type)
        # A single complete price is only a point-in-time quote, not an
        # official odds history. Cold-result research requires at least two
        # complete Sporttery captures for the same market and handicap line.
        if actual_result is None or len(snapshots) < 2:
            continue
        snapshots.sort(key=lambda item: item[0])
        opening_time, opening_odds = snapshots[0]
        closing_time, closing_odds = snapshots[-1]
        try:
            signal = calculate_market_signal(
                play_type=play_type,
                odds_by_option=closing_odds,
                actual_result=actual_result,
                rule=rule,
            )
        except IncompleteMarketError:
            continue
        detections.append(
            MarketDetection(
                play_type=play_type,
                handicap=handicap,
                opening_snapshot_time=opening_time,
                closing_snapshot_time=closing_time,
                opening_odds=opening_odds,
                closing_odds=closing_odds,
                signal=signal,
                actual_odds_change_rate=_odds_change(
                    opening_odds.get(signal.actual_option),
                    closing_odds.get(signal.actual_option),
                ),
            )
        )

    return sorted(
        detections,
        key=lambda detection: (
            detection.signal.actual_probability,
            detection.play_type,
            detection.handicap if detection.handicap is not None else 9999,
        ),
    )
