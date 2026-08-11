from __future__ import annotations

from datetime import UTC, datetime

from scripts.jobs.collect_news_intelligence import (
    build_collection_clients,
    build_watch_query,
    collect_from_clients,
    run,
)


def test_watch_query_is_bounded_for_gnews_and_uses_exact_team_phrases() -> None:
    matches = [{"home_team_name": f"主队{i}", "away_team_name": f"客队{i}"} for i in range(30)]

    query = build_watch_query(matches)

    assert len(query) <= 190
    assert '"主队0"' in query
    assert " OR " in query


def test_collection_is_disabled_by_default_even_when_imported(monkeypatch) -> None:
    monkeypatch.delenv("FQP_NEWS_COLLECTION_ENABLED", raising=False)
    monkeypatch.setenv("NEWSAPI_API_KEY", "must-not-be-used")

    result = run()

    assert result == {"status": "skipped", "reason": "collection_disabled"}


def test_guardian_client_is_added_only_when_its_key_is_configured() -> None:
    clients = build_collection_clients({"newsapi": "", "gnews": "", "guardian": "key"})

    assert [client.provider_code for client in clients] == ["guardian"]


def test_one_provider_failure_does_not_discard_other_provider_results() -> None:
    class _GoodClient:
        provider_code = "good"

        def search(self, *_args, **_kwargs):
            return [object()]

    class _BrokenClient:
        provider_code = "broken"

        def search(self, *_args, **_kwargs):
            raise RuntimeError("temporary upstream failure")

    result = collect_from_clients(
        [_BrokenClient(), _GoodClient()],
        query="Team",
        matches=[{"id": 1}],
        observed_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
        store=lambda _candidates: {"inserted": 1, "duplicates": 0, "linked": 1, "filtered": 0},
    )

    assert result["status"] == "partial"
    assert result["providers"] == 1
    assert result["failedProviders"] == 1
    assert result["inserted"] == 1
