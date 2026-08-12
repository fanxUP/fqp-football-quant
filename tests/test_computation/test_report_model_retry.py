from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.backend.src.services.report_automation import _report_attempt_gate


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _query: str, _params: tuple[object, ...]) -> None:
        return None

    def fetchone(self) -> tuple[object, ...] | None:
        return self.row


class _Connection:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row

    def cursor(self) -> _Cursor:
        return _Cursor(self.row)


def test_failed_automatic_report_waits_before_retrying() -> None:
    now = datetime(2026, 8, 12, 6, tzinfo=UTC)
    allowed, reason = _report_attempt_gate(
        _Connection(("failed", 1, now - timedelta(minutes=30))),
        source_type="post_daily",
        source_ref="2026-08-11",
        now=now,
    )

    assert allowed is False
    assert reason == "retry_cooldown"


def test_failed_automatic_report_retries_after_cooldown_but_stops_at_three_attempts() -> None:
    now = datetime(2026, 8, 12, 6, tzinfo=UTC)
    assert _report_attempt_gate(
        _Connection(("failed", 1, now - timedelta(hours=3))),
        source_type="post_daily",
        source_ref="2026-08-11",
        now=now,
    ) == (True, None)
    assert _report_attempt_gate(
        _Connection(("failed", 3, now - timedelta(hours=3))),
        source_type="post_daily",
        source_ref="2026-08-11",
        now=now,
    ) == (False, "retry_exhausted")
