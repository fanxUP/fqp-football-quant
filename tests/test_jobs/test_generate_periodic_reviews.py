from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

from scripts.jobs.generate_periodic_reviews import (
    _aggregate_review_rows,
    _load_completed_daily_snapshots,
)


def test_periodic_review_loads_only_completed_daily_snapshots() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.query = ""
            self.params: tuple[object, ...] = ()

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute(self, query: str, params: tuple[object, ...]) -> None:
            self.query = query
            self.params = params

        def fetchall(self):
            return [("2026-08-09", {"researchMetrics": {"matchCount": 2}})]

    class Connection:
        def __init__(self) -> None:
            self.cursor_instance = Cursor()

        def cursor(self) -> Cursor:
            return self.cursor_instance

    conn = Connection()
    snapshots = _load_completed_daily_snapshots(conn, "2026-08-03", "2026-08-09")

    assert "report_type = 'daily'" in conn.cursor_instance.query
    assert "status = 'completed'" in conn.cursor_instance.query
    assert conn.cursor_instance.params == ("2026-08-03", "2026-08-09")
    assert snapshots == [{"periodKey": "2026-08-09", "researchMetrics": {"matchCount": 2}}]


def test_periodic_review_uses_weighted_roi_and_true_drawdown():
    aggregate = _aggregate_review_rows(
        [
            ("2026-07-04", 100, 140, 40),
            ("2026-07-02", 10, 0, -10),
            ("2026-07-01", 100, 130, 30),
            ("2026-07-03", 10, 0, -10),
        ]
    )

    assert aggregate["total_stake"] == 220.0
    assert aggregate["profit_loss"] == 50.0
    assert aggregate["roi"] == 0.2273
    assert aggregate["max_drawdown"] == 20.0
    assert aggregate["losing_days_count"] == 2
    assert aggregate["longest_losing_streak"] == 2


def test_periodic_review_handles_no_stake_without_fake_roi():
    aggregate = _aggregate_review_rows([])

    assert aggregate["roi"] == 0.0
    assert aggregate["max_drawdown"] == 0.0


def test_periodic_reviews_generate_weekly_and_monthly_upset_reports():
    source = Path("scripts/jobs/generate_periodic_reviews.py").read_text()

    assert 'report_type="weekly"' in source
    assert 'report_type="monthly"' in source


def test_periodic_reviews_request_one_automatic_interpretation_per_completed_period():
    source = Path("scripts/jobs/generate_periodic_reviews.py").read_text()

    assert 'source_type="post_weekly"' in source
    assert 'source_type="post_monthly"' in source


def test_weekly_review_defers_without_writing_business_review(monkeypatch) -> None:
    from scripts.jobs import generate_periodic_reviews

    @contextmanager
    def fake_db():
        yield object()

    writes: list[dict[str, object]] = []
    monkeypatch.setattr(generate_periodic_reviews, "get_db", fake_db)
    monkeypatch.setattr(
        generate_periodic_reviews,
        "assess_periodic_report_readiness",
        lambda _conn, **_kwargs: {
            "canGenerate": False,
            "status": "waiting",
            "reasonCodes": ["DAILY_REPORT_PENDING"],
        },
    )
    monkeypatch.setattr(
        generate_periodic_reviews,
        "has_completed_report_generation_run",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        generate_periodic_reviews,
        "upsert_report_generation_run",
        lambda _conn, **kwargs: writes.append(kwargs),
    )

    result = generate_periodic_reviews.run_weekly("2026-08-03", "2026-08-09")

    assert result == {
        "status": "waiting",
        "week_start": "2026-08-03",
        "week_end": "2026-08-09",
        "readiness": {
            "canGenerate": False,
            "status": "waiting",
            "reasonCodes": ["DAILY_REPORT_PENDING"],
        },
    }
    assert writes == [
        {
            "report_type": "weekly",
            "period_key": "2026-08-03",
            "status": "waiting",
            "readiness": {
                "canGenerate": False,
                "status": "waiting",
                "reasonCodes": ["DAILY_REPORT_PENDING"],
            },
        }
    ]


def test_monthly_review_does_not_overwrite_completed_snapshot(monkeypatch) -> None:
    from scripts.jobs import generate_periodic_reviews

    @contextmanager
    def fake_db():
        yield object()

    monkeypatch.setattr(generate_periodic_reviews, "get_db", fake_db)
    monkeypatch.setattr(
        generate_periodic_reviews,
        "assess_periodic_report_readiness",
        lambda _conn, **_kwargs: {"canGenerate": True, "status": "ready"},
    )
    monkeypatch.setattr(
        generate_periodic_reviews,
        "has_completed_report_generation_run",
        lambda *_args, **_kwargs: True,
    )
    retry = MagicMock(return_value={"status": "skipped", "reason": "retry_cooldown"})
    monkeypatch.setattr(
        generate_periodic_reviews, "retry_completed_report_interpretation", retry
    )
    monkeypatch.setattr(
        generate_periodic_reviews,
        "upsert_monthly_review",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not overwrite review")
        ),
    )

    result = generate_periodic_reviews.run_monthly("2026-07")

    assert result == {
        "status": "skipped",
        "month": "2026-07",
        "reason": "already_completed",
    }
    retry.assert_called_once()
