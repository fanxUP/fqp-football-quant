from __future__ import annotations

from datetime import datetime

from scripts.upset.detector import build_market_detections, canonical_odds_option
from scripts.upset.domain import UpsetRule


def _row(
    snapshot_id: int,
    at: str,
    play_type: str,
    option_code: str,
    odds: float,
    handicap: float | None = None,
) -> tuple:
    return (
        snapshot_id,
        datetime.fromisoformat(at),
        play_type,
        option_code,
        odds,
        handicap,
    )


def test_canonicalizes_official_one_x_two_odds_codes():
    assert canonical_odds_option("spf", "h") == "3"
    assert canonical_odds_option("spf", "d") == "1"
    assert canonical_odds_option("rqspf", "a") == "0"
    assert canonical_odds_option("bf", "2:1") == "2:1"


def test_selects_first_and_last_complete_snapshot_without_mixing_timestamps():
    rows = [
        _row(1, "2026-07-20T09:00:00", "spf", "h", 1.50),
        _row(2, "2026-07-20T09:00:00", "spf", "d", 3.90),
        _row(3, "2026-07-20T09:00:00", "spf", "a", 6.20),
        _row(4, "2026-07-20T11:00:00", "spf", "h", 1.55),
        _row(5, "2026-07-20T11:00:00", "spf", "d", 3.80),
        # Incomplete 11:00 group must not become closing market.
        _row(6, "2026-07-20T12:00:00", "spf", "h", 1.60),
        _row(7, "2026-07-20T12:00:00", "spf", "d", 3.70),
        _row(8, "2026-07-20T12:00:00", "spf", "a", 5.80),
    ]

    detections = build_market_detections(
        odds_rows=rows,
        result_by_play={"spf": "A"},
        rule=UpsetRule.default(),
    )

    assert len(detections) == 1
    detection = detections[0]
    assert detection.opening_snapshot_time == datetime(2026, 7, 20, 9)
    assert detection.closing_snapshot_time == datetime(2026, 7, 20, 12)
    assert detection.opening_odds == {"3": 1.50, "1": 3.90, "0": 6.20}
    assert detection.closing_odds == {"3": 1.60, "1": 3.70, "0": 5.80}
    assert detection.signal.actual_option == "0"


def test_keeps_different_handicap_lines_in_separate_markets():
    rows = [
        *[
            _row(index, "2026-07-20T10:00:00", "rqspf", code, odds, -1)
            for index, (code, odds) in enumerate(
                [("h", 2.50), ("d", 3.40), ("a", 2.20)], start=1
            )
        ],
        *[
            _row(index, "2026-07-20T10:00:00", "rqspf", code, odds, 1)
            for index, (code, odds) in enumerate(
                [("h", 1.20), ("d", 4.80), ("a", 8.50)], start=10
            )
        ],
        *[
            _row(index, "2026-07-20T11:00:00", "rqspf", code, odds, -1)
            for index, (code, odds) in enumerate(
                [("h", 2.45), ("d", 3.45), ("a", 2.25)], start=20
            )
        ],
        *[
            _row(index, "2026-07-20T11:00:00", "rqspf", code, odds, 1)
            for index, (code, odds) in enumerate(
                [("h", 1.22), ("d", 4.70), ("a", 8.20)], start=30
            )
        ],
    ]

    detections = build_market_detections(
        odds_rows=rows,
        result_by_play={"rqspf": "0"},
        rule=UpsetRule.default(),
    )

    assert {detection.handicap for detection in detections} == {-1.0, 1.0}


def test_ignores_market_without_result_or_complete_option_set():
    detections = build_market_detections(
        odds_rows=[
            _row(1, "2026-07-20T09:00:00", "spf", "h", 1.50),
            _row(2, "2026-07-20T09:00:00", "spf", "d", 3.90),
        ],
        result_by_play={"spf": None},
        rule=UpsetRule.default(),
    )

    assert detections == []


def test_requires_two_complete_official_snapshots_before_detecting_upset():
    rows = [
        _row(1, "2026-07-20T09:00:00", "spf", "h", 1.50),
        _row(2, "2026-07-20T09:00:00", "spf", "d", 3.90),
        _row(3, "2026-07-20T09:00:00", "spf", "a", 6.20),
        # A partial later capture is not an official historical market.
        _row(4, "2026-07-20T10:00:00", "spf", "h", 1.55),
        _row(5, "2026-07-20T10:00:00", "spf", "d", 3.80),
    ]

    detections = build_market_detections(
        odds_rows=rows,
        result_by_play={"spf": "0"},
        rule=UpsetRule.default(),
    )

    assert detections == []
