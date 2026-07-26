from pathlib import Path

from scripts.jobs.generate_periodic_reviews import _aggregate_review_rows


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
