from __future__ import annotations

from datetime import UTC, datetime

from scripts.jobs.collect_news_intelligence import (
    build_collection_clients,
    collect_from_clients,
    collect_provider_batches,
    run,
)
from scripts.news_query_planner import NewsQueryBatch


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


def test_provider_batches_record_each_request_and_keep_zero_results_visible() -> None:
    class _Client:
        provider_code = "gnews"

        def search(self, query, **_kwargs):
            return [] if query == "empty" else [object()]

    audits: list[dict[str, object]] = []
    result = collect_provider_batches(
        _Client(),
        [
            NewsQueryBatch("empty", (1,), ({"id": 1},)),
            NewsQueryBatch("found", (2,), ({"id": 2},)),
        ],
        observed_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
        store=lambda candidates, _matches: {
            "inserted": len(candidates),
            "duplicates": 0,
            "linked": len(candidates),
            "filtered": 0,
        },
        audit=audits.append,
        wait=lambda _seconds: None,
    )

    assert result["requests"] == 2
    assert result["zeroResultQueries"] == 1
    assert result["inserted"] == 1
    assert [audit["status"] for audit in audits] == ["completed", "completed"]


def test_newsapi_free_tier_is_not_automated_in_production_without_explicit_opt_in(
    monkeypatch,
) -> None:
    monkeypatch.setenv("FQP_NEWS_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("NEWSAPI_API_KEY", "configured")
    monkeypatch.delenv("FQP_NEWSAPI_AUTOMATION_ENABLED", raising=False)
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    monkeypatch.delenv("GUARDIAN_API_KEY", raising=False)

    result = run()

    assert result == {
        "status": "skipped",
        "reason": "no_eligible_provider_keys",
        "skippedProviders": [
            {"provider": "newsapi", "reason": "free_plan_development_only"}
        ],
    }
