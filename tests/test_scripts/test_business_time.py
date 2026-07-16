from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import patch

from scripts.business_time import business_now, business_today, business_yesterday
from scripts.jobs import settle_finished_matches


def test_business_date_rolls_over_at_shanghai_midnight():
    utc_evening = datetime(2026, 7, 14, 20, 30, tzinfo=UTC)

    assert business_now(utc_evening).isoformat() == "2026-07-15T04:30:00+08:00"
    assert business_today(utc_evening) == date(2026, 7, 15)
    assert business_yesterday(utc_evening) == date(2026, 7, 14)


def test_result_settlement_uses_business_dates_during_utc_evening():
    utc_evening = datetime(2026, 7, 14, 20, 30, tzinfo=UTC)
    expected = {"status": "ok", "results_found": 0}

    with patch(
        "scripts.jobs.settle_finished_matches.crawl_official_results",
        return_value=expected,
    ) as crawl:
        result = settle_finished_matches.run(now=utc_evening)

    assert result == expected
    crawl.assert_called_once_with(begin_date="2026-07-12", end_date="2026-07-15")


def test_business_time_sql_is_used_for_naive_match_timestamps():
    files = [
        "apps/backend/src/routers/simulator.py",
        "apps/backend/src/routers/predictions.py",
        "apps/backend/src/routers/teams.py",
        "scripts/jobs/run_model_prediction.py",
        "scripts/jobs/run_recommendation_candidate.py",
    ]

    for file in files:
        source = Path(file).read_text(encoding="utf-8")
        assert "timezone('Asia/Shanghai', NOW())" in source, file
        assert "CURRENT_TIMESTAMP" not in source, file
        assert "m.kickoff_time > NOW()" not in source, file
