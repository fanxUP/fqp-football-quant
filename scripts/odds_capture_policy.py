"""Pure scheduling and completeness rules for official odds captures."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

BUSINESS_TIMEZONE = ZoneInfo("Asia/Shanghai")
CAPTURE_INTERVAL = timedelta(minutes=30)
PARTIAL_RETRY_INTERVAL = timedelta(minutes=5)
FINAL_CAPTURE_GRACE = timedelta(minutes=10)

CANONICAL_PLAY_TYPES = ("spf", "rqspf", "bf", "zjq", "bqc")
EXPECTED_OPTION_COUNTS = {"spf": 3, "rqspf": 3, "bf": 31, "zjq": 8, "bqc": 9}


@dataclass(frozen=True)
class CaptureCandidate:
    match_id: int
    kickoff_time: datetime
    last_attempt_at: datetime | None
    last_attempt_status: str | None
    final_attempted: bool


@dataclass(frozen=True)
class CaptureDecision:
    is_due: bool
    capture_kind: str | None = None
    scheduled_for: datetime | None = None
    reason: str | None = None


@dataclass(frozen=True)
class CaptureCompleteness:
    status: str
    captured_play_types: tuple[str, ...]
    missing_play_types: tuple[str, ...]


def as_business_time(value: datetime) -> datetime:
    """Interpret official naive timestamps as Shanghai local business time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=BUSINESS_TIMEZONE)
    return value.astimezone(BUSINESS_TIMEZONE)


def capture_decision(candidate: CaptureCandidate, now: datetime) -> CaptureDecision:
    """Return the next action without performing I/O.

    The final attempt is tied to kickoff, so it remains distinct from periodic
    captures even when kickoff happens on a half-hour boundary.
    """
    current = as_business_time(now)
    kickoff = as_business_time(candidate.kickoff_time)

    if current >= kickoff:
        if candidate.final_attempted:
            return CaptureDecision(False, reason="final_already_attempted")
        if current <= kickoff + FINAL_CAPTURE_GRACE:
            return CaptureDecision(True, "final", kickoff)
        return CaptureDecision(False, reason="kickoff_grace_expired")

    if candidate.last_attempt_at is None:
        return CaptureDecision(True, "opening", current)

    last_attempt = as_business_time(candidate.last_attempt_at)
    if candidate.last_attempt_status in {"partial", "failed", "running"}:
        if current >= last_attempt + PARTIAL_RETRY_INTERVAL:
            return CaptureDecision(True, "retry", current)
        return CaptureDecision(False, reason="retry_not_due")

    if current >= last_attempt + CAPTURE_INTERVAL:
        return CaptureDecision(True, "periodic", current)
    return CaptureDecision(False, reason="periodic_not_due")


def evaluate_capture_completeness(
    expected_play_types: Iterable[str],
    snapshots: list[dict],
) -> CaptureCompleteness:
    """Validate that every officially offered play has its canonical options."""
    requested = set(expected_play_types)
    expected = tuple(play_type for play_type in CANONICAL_PLAY_TYPES if play_type in requested)
    if not expected:
        return CaptureCompleteness("not_offered", (), ())

    option_counts = Counter(
        (snapshot.get("play_type"), snapshot.get("option_code")) for snapshot in snapshots
    )
    captured: list[str] = []
    missing: list[str] = []
    for play_type in expected:
        count = sum(1 for key in option_counts if key[0] == play_type)
        if count >= EXPECTED_OPTION_COUNTS[play_type]:
            captured.append(play_type)
        else:
            missing.append(play_type)

    status = "complete" if not missing else "partial"
    return CaptureCompleteness(status, tuple(captured), tuple(missing))
