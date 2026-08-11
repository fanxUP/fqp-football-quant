from __future__ import annotations

from scripts.jobs.collect_news_intelligence import build_watch_query, run


def test_watch_query_is_bounded_for_gnews_and_uses_exact_team_phrases() -> None:
    matches = [
        {"home_team_name": f"主队{i}", "away_team_name": f"客队{i}"}
        for i in range(30)
    ]

    query = build_watch_query(matches)

    assert len(query) <= 190
    assert '"主队0"' in query
    assert " OR " in query


def test_collection_is_disabled_by_default_even_when_imported(monkeypatch) -> None:
    monkeypatch.delenv("FQP_NEWS_COLLECTION_ENABLED", raising=False)
    monkeypatch.setenv("NEWSAPI_API_KEY", "must-not-be-used")

    result = run()

    assert result == {"status": "skipped", "reason": "collection_disabled"}
