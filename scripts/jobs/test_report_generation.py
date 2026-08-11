from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from scripts.jobs.report_generation import (
    assess_daily_report_readiness,
    assess_periodic_report_readiness,
    replace_completed_report_snapshot_with_revision,
)


class _Cursor:
    def __init__(self) -> None:
        self._row: tuple[object, ...] = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def execute(self, query: str, _params: tuple[object, ...]) -> None:
        if "confirmed_result_count" in query:
            self._row = (3, 3, datetime(2026, 8, 9, 18, 0))
        elif "unsettled_ticket_count" in query:
            self._row = (0,)
        else:
            raise AssertionError(f"Unexpected query: {query}")

    def fetchone(self) -> tuple[object, ...]:
        return self._row


class _Connection:
    def cursor(self) -> _Cursor:
        return _Cursor()


def test_daily_report_waits_for_post_match_window_before_generating() -> None:
    readiness = assess_daily_report_readiness(
        _Connection(),
        "2026-08-09",
        now=datetime(2026, 8, 9, 21, 59),
    )

    assert readiness == {
        "canGenerate": False,
        "status": "waiting",
        "reasonCodes": ["POST_MATCH_WINDOW_OPEN"],
        "officialMatchCount": 3,
        "confirmedResultCount": 3,
        "unsettledTicketCount": 0,
        "latestKickoffTime": "2026-08-09T18:00:00",
        "eligibleAt": "2026-08-09T22:00:00",
    }


def test_daily_report_requires_confirmed_results_and_ticket_settlement() -> None:
    class _PendingCursor(_Cursor):
        def execute(self, query: str, _params: tuple[object, ...]) -> None:
            if "confirmed_result_count" in query:
                self._row = (3, 2, datetime(2026, 8, 9, 18, 0))
            elif "unsettled_ticket_count" in query:
                self._row = (1,)
            else:
                raise AssertionError(f"Unexpected query: {query}")

    class _PendingConnection:
        def cursor(self) -> _PendingCursor:
            return _PendingCursor()

    readiness = assess_daily_report_readiness(
        _PendingConnection(),
        "2026-08-09",
        now=datetime(2026, 8, 10, 1, 0),
    )

    assert readiness["canGenerate"] is False
    assert readiness["reasonCodes"] == ["OFFICIAL_RESULT_PENDING", "TICKET_SETTLEMENT_PENDING"]


def test_daily_report_skips_empty_official_day() -> None:
    class _EmptyCursor(_Cursor):
        def execute(self, query: str, _params: tuple[object, ...]) -> None:
            if "confirmed_result_count" in query:
                self._row = (0, 0, None)
            elif "unsettled_ticket_count" in query:
                self._row = (0,)
            else:
                raise AssertionError(f"Unexpected query: {query}")

    class _EmptyConnection:
        def cursor(self) -> _EmptyCursor:
            return _EmptyCursor()

    readiness = assess_daily_report_readiness(_EmptyConnection(), "2026-08-09")

    assert readiness["canGenerate"] is False
    assert readiness["status"] == "skipped"
    assert readiness["reasonCodes"] == ["NO_OFFICIAL_MATCHES"]


def test_periodic_report_waits_for_every_official_day_daily_report() -> None:
    class _PeriodicCursor(_Cursor):
        def execute(self, query: str, _params: tuple[object, ...]) -> None:
            if "completed_daily_report_count" in query:
                self._row = (3, 2, ["2026-08-04"])
            else:
                raise AssertionError(f"Unexpected query: {query}")

    class _PeriodicConnection:
        def cursor(self) -> _PeriodicCursor:
            return _PeriodicCursor()

    readiness = assess_periodic_report_readiness(
        _PeriodicConnection(),
        start="2026-08-03",
        end="2026-08-09",
    )

    assert readiness == {
        "canGenerate": False,
        "status": "waiting",
        "reasonCodes": ["DAILY_REPORT_PENDING"],
        "officialDayCount": 3,
        "completedDailyReportCount": 2,
        "pendingDailyReportDates": ["2026-08-04"],
        "periodStart": "2026-08-03",
        "periodEnd": "2026-08-09",
    }


def test_periodic_report_skips_period_without_official_matches() -> None:
    class _EmptyPeriodicCursor(_Cursor):
        def execute(self, query: str, _params: tuple[object, ...]) -> None:
            if "completed_daily_report_count" in query:
                self._row = (0, 0, [])
            else:
                raise AssertionError(f"Unexpected query: {query}")

    class _EmptyPeriodicConnection:
        def cursor(self) -> _EmptyPeriodicCursor:
            return _EmptyPeriodicCursor()

    readiness = assess_periodic_report_readiness(
        _EmptyPeriodicConnection(),
        start="2026-07-01",
        end="2026-07-31",
    )

    assert readiness["status"] == "skipped"
    assert readiness["reasonCodes"] == ["NO_OFFICIAL_MATCHES"]


def test_daily_review_job_defers_without_writing_business_review(monkeypatch) -> None:
    from scripts.jobs import generate_daily_review

    @contextmanager
    def fake_db():
        yield _Connection()

    writes: list[dict[str, object]] = []
    monkeypatch.setattr(generate_daily_review, "get_db", fake_db)
    monkeypatch.setattr(
        generate_daily_review,
        "assess_daily_report_readiness",
        lambda _conn, _date: {
            "canGenerate": False,
            "status": "waiting",
            "reasonCodes": ["OFFICIAL_RESULT_PENDING"],
        },
    )
    monkeypatch.setattr(
        generate_daily_review,
        "has_completed_report_generation_run",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        generate_daily_review,
        "upsert_report_generation_run",
        lambda _conn, **kwargs: writes.append(kwargs),
    )

    result = generate_daily_review._run_impl("2026-08-09")

    assert result == {
        "status": "waiting",
        "review_date": "2026-08-09",
        "readiness": {
            "canGenerate": False,
            "status": "waiting",
            "reasonCodes": ["OFFICIAL_RESULT_PENDING"],
        },
    }
    assert writes == [
        {
            "report_type": "daily",
            "period_key": "2026-08-09",
            "status": "waiting",
            "readiness": {
                "canGenerate": False,
                "status": "waiting",
                "reasonCodes": ["OFFICIAL_RESULT_PENDING"],
            },
        }
    ]


def test_daily_review_tracks_waiting_as_successful_scheduler_check(monkeypatch) -> None:
    from scripts.jobs import generate_daily_review

    finished: list[tuple[object, str, dict[str, object]]] = []
    monkeypatch.setattr(generate_daily_review, "start_tracked_job", lambda *_args: 42)
    monkeypatch.setattr(
        generate_daily_review,
        "_run_impl",
        lambda **_kwargs: {"status": "waiting", "review_date": "2026-08-09"},
    )
    monkeypatch.setattr(
        generate_daily_review,
        "finish_tracked_job",
        lambda run_id, status, output: finished.append((run_id, status, output)),
    )

    result = generate_daily_review.run(review_date="2026-08-09")

    assert result["status"] == "waiting"
    assert finished == [(42, "ok", {"result": result})]


def test_daily_review_does_not_overwrite_completed_snapshot(monkeypatch) -> None:
    from scripts.jobs import generate_daily_review

    @contextmanager
    def fake_db():
        yield _Connection()

    monkeypatch.setattr(generate_daily_review, "get_db", fake_db)
    monkeypatch.setattr(
        generate_daily_review,
        "assess_daily_report_readiness",
        lambda _conn, _date: {"canGenerate": True, "status": "ready"},
    )
    monkeypatch.setattr(
        generate_daily_review,
        "has_completed_report_generation_run",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        generate_daily_review,
        "upsert_daily_review",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not overwrite review")
        ),
    )

    result = generate_daily_review._run_impl("2026-08-09")

    assert result == {
        "status": "skipped",
        "review_date": "2026-08-09",
        "reason": "already_completed",
    }


def test_snapshot_backfill_archives_old_snapshot_before_replacing_completed_run() -> None:
    class _RevisionCursor:
        def __init__(self) -> None:
            self.row: tuple[object, ...] | None = None
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, query: str, _params: tuple[object, ...]) -> None:
            self.statements.append(query)
            if "FOR UPDATE" in query:
                self.row = ({"schemaVersion": 3}, "old-hash")
            elif "MAX(revision)" in query:
                self.row = (2,)
            else:
                self.row = None

        def fetchone(self):
            return self.row

    class _RevisionConnection:
        def __init__(self) -> None:
            self.cursor_instance = _RevisionCursor()
            self.committed = False

        def cursor(self):
            return self.cursor_instance

        def commit(self) -> None:
            self.committed = True

    conn = _RevisionConnection()
    result = replace_completed_report_snapshot_with_revision(
        conn,
        report_type="daily",
        period_key="2026-08-09",
        snapshot={"schemaVersion": 4, "performanceMetrics": {"sampleCount": 3}},
        reason="升级真实表现指标",
    )

    assert result["revision"] == 2
    assert result["previousSnapshotHash"] == "old-hash"
    assert len(result["snapshotHash"]) == 64
    assert any(
        "INSERT INTO report_generation_revisions" in query
        for query in conn.cursor_instance.statements
    )
    assert any(
        "UPDATE report_generation_runs" in query for query in conn.cursor_instance.statements
    )
    assert conn.committed is True
