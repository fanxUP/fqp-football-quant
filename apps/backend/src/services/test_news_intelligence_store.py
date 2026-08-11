from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from apps.backend.src.services.news_intelligence_store import get_news_overview


def test_overview_exposes_ai_screening_health_without_model_content() -> None:
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (
        12,
        4,
        3,
        2,
        datetime(2026, 8, 11, 1, tzinfo=UTC),
        False,
        10,
        7,
        1,
        2,
        datetime(2026, 8, 11, 1, 5, tzinfo=UTC),
        True,
    )

    overview = get_news_overview(conn)

    assert overview["screeningCount"] == 10
    assert overview["aiScreeningCount"] == 7
    assert overview["modelFailureCount"] == 1
    assert overview["pendingReviewCount"] == 2
    assert overview["newsAgentReady"] is True
    assert "response" not in overview
