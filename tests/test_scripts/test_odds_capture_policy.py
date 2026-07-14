from datetime import datetime
from zoneinfo import ZoneInfo

from scripts.odds_capture_policy import (
    CaptureCandidate,
    capture_decision,
    evaluate_capture_completeness,
)

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=SHANGHAI)


def test_first_observed_open_market_is_captured_immediately():
    candidate = CaptureCandidate(
        match_id=7,
        kickoff_time=_at("2026-07-14T19:15:00"),
        last_attempt_at=None,
        last_attempt_status=None,
        final_attempted=False,
    )

    decision = capture_decision(candidate, _at("2026-07-14T17:12:00"))

    assert decision.is_due is True
    assert decision.capture_kind == "opening"


def test_periodic_capture_waits_for_thirty_minutes():
    candidate = CaptureCandidate(
        match_id=7,
        kickoff_time=_at("2026-07-14T19:15:00"),
        last_attempt_at=_at("2026-07-14T17:12:00"),
        last_attempt_status="complete",
        final_attempted=False,
    )

    assert capture_decision(candidate, _at("2026-07-14T17:41:59")).is_due is False
    assert capture_decision(candidate, _at("2026-07-14T17:42:00")).capture_kind == "periodic"


def test_partial_capture_retries_after_five_minutes():
    candidate = CaptureCandidate(
        match_id=7,
        kickoff_time=_at("2026-07-14T19:15:00"),
        last_attempt_at=_at("2026-07-14T17:12:00"),
        last_attempt_status="partial",
        final_attempted=False,
    )

    assert capture_decision(candidate, _at("2026-07-14T17:16:59")).is_due is False
    assert capture_decision(candidate, _at("2026-07-14T17:17:00")).capture_kind == "retry"


def test_kickoff_is_a_distinct_final_capture_and_never_repeats():
    candidate = CaptureCandidate(
        match_id=7,
        kickoff_time=_at("2026-07-14T19:15:00"),
        last_attempt_at=_at("2026-07-14T19:00:00"),
        last_attempt_status="complete",
        final_attempted=False,
    )

    decision = capture_decision(candidate, _at("2026-07-14T19:15:00"))
    assert decision.capture_kind == "final"
    assert decision.scheduled_for == _at("2026-07-14T19:15:00")

    already_attempted = CaptureCandidate(
        match_id=7,
        kickoff_time=candidate.kickoff_time,
        last_attempt_at=candidate.last_attempt_at,
        last_attempt_status="failed",
        final_attempted=True,
    )
    assert capture_decision(already_attempted, _at("2026-07-14T19:16:00")).is_due is False


def test_all_offered_play_types_require_complete_option_sets():
    snapshots = []
    expected_counts = {"spf": 3, "rqspf": 3, "bf": 31, "zjq": 8, "bqc": 9}
    for play_type, count in expected_counts.items():
        snapshots.extend(
            {"play_type": play_type, "option_code": str(index)} for index in range(count)
        )

    result = evaluate_capture_completeness(expected_counts.keys(), snapshots)

    assert result.status == "complete"
    assert result.captured_play_types == tuple(expected_counts)
    assert result.missing_play_types == ()


def test_missing_offered_play_is_partial_and_no_offered_play_is_not_offered():
    partial = evaluate_capture_completeness(
        ["spf", "rqspf"],
        [
            {"play_type": "spf", "option_code": "h"},
            {"play_type": "spf", "option_code": "d"},
            {"play_type": "spf", "option_code": "a"},
        ],
    )
    not_offered = evaluate_capture_completeness([], [])

    assert partial.status == "partial"
    assert partial.missing_play_types == ("rqspf",)
    assert not_offered.status == "not_offered"
