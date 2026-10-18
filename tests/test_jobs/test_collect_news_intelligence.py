from __future__ import annotations

from datetime import UTC, datetime

from scripts.jobs.collect_news_intelligence import (
    build_collection_clients,
    collect_from_clients,
    collect_provider_batches,
    run,
)
from scripts.news_intelligence_clients import NewsArticleCandidate
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
            if query == "empty":
                return []
            return [
                NewsArticleCandidate(
                    provider_code="gnews",
                    external_id="found",
                    source_name="Sports Desk",
                    source_domain="sports.example",
                    canonical_url="https://sports.example/found",
                    title="Team found update",
                    description="Team found is preparing for the match.",
                    language="en",
                    published_at=datetime(2026, 8, 10, 7, tzinfo=UTC),
                    raw_metadata={},
                )
            ]

    audits: list[dict[str, object]] = []
    result = collect_provider_batches(
        _Client(),
        [
            NewsQueryBatch(
                "empty",
                (1,),
                ({"id": 1, "home_search_terms": ["Empty"], "away_search_terms": []},),
            ),
            NewsQueryBatch(
                "found",
                (2,),
                ({"id": 2, "home_search_terms": ["Team found"], "away_search_terms": []},),
            ),
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
        "skippedProviders": [{"provider": "newsapi", "reason": "free_plan_development_only"}],
    }


def test_audit_distinguishes_blocked_batches_from_actual_transport_sends(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    import httpx

    from scripts.news_intelligence_clients import GNewsClient
    from scripts.request_quota import QuotaDenied

    ledger = MagicMock(policy=SimpleNamespace(provider="gnews", day_reset_offset_seconds=0))
    ledger.reserve.side_effect = ["permit", QuotaDenied("day_exhausted")]
    ledger.mark_sent.return_value = SimpleNamespace(day_sent=1)
    transport = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"articles": []}))
    )
    client = GNewsClient("test-secret", client=transport, ledger=ledger)
    monkeypatch.setattr(client._transport, "_wait", lambda _: None)
    audits = []
    result = collect_provider_batches(
        client,
        [NewsQueryBatch("A", (1,), ()), NewsQueryBatch("B", (2,), ())],
        observed_at=datetime(2026, 10, 16, tzinfo=UTC),
        store=lambda *_: {},
        audit=audits.append,
        wait=lambda _: None,
    )
    assert result["requests"] == 2
    assert result["sentRequests"] == result["blockedRequests"] == 1
    assert result["unmeasuredRequests"] == 0
    assert result["failedRequests"] == 1
    assert [item["cursor_state"]["transport"]["attemptsSent"] for item in audits] == [1, 0]
    assert "test-secret" not in str(audits)
    client.close()
    transport.close()


def test_legacy_clients_without_transport_counters_are_marked_unmeasured():
    class Legacy:
        provider_code = "guardian"

        def search(self, *_args, **_kwargs):
            return []

    audits = []
    result = collect_provider_batches(
        Legacy(),
        [NewsQueryBatch("A", (1,), ())],
        observed_at=datetime(2026, 10, 16, tzinfo=UTC),
        store=lambda *_: {},
        audit=audits.append,
    )
    assert result["unmeasuredRequests"] == 1
    assert result["sentRequests"] == 0
    assert audits[0]["cursor_state"]["transport"] == {"attemptsSent": None, "measured": False}


def test_run_does_not_use_completed_audit_counts_as_send_permission(monkeypatch):
    from contextlib import contextmanager

    from scripts.jobs import collect_news_intelligence as job

    monkeypatch.setenv("FQP_NEWS_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("GUARDIAN_API_KEY", "test-secret")
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    monkeypatch.delenv("GNEWS_API_KEY", raising=False)
    in_db = False

    @contextmanager
    def db():
        nonlocal in_db
        assert not in_db
        in_db = True
        try:
            yield object()
        finally:
            in_db = False

    class Client:
        provider_code = "guardian"
        total_sends = 0
        closed = False

        def search(self, *_args, **_kwargs):
            assert not in_db
            return []

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(job, "get_db", db)
    monkeypatch.setattr(job, "load_news_watch_matches", lambda _: [{"id": 1}])
    monkeypatch.setattr(job, "build_collection_clients", lambda _: [client])
    monkeypatch.setattr(
        job,
        "build_provider_query_batches",
        lambda *_args, **_kwargs: [NewsQueryBatch("A", (1,), ())],
    )
    monkeypatch.setattr(job, "store_news_candidates", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(job, "record_news_ingestion_request", lambda *_: None)
    result = job.run()
    assert result["providers"]["guardian"]["quotaSource"] == "shared_account_ledger"
    assert "usedRequests" not in result["providers"]["guardian"]
    assert client.closed


def test_reuse_audit_keeps_original_acquisition_and_counts_no_new_send():
    class Client:
        provider_code = "gnews"
        total_sends = 0
        last_request_meta = {
            "reuse_status": "cache_hit",
            "fetched_at_ms": 1000,
            "age_ms": 500,
            "url": "secret-url",
            "body": "secret-body",
        }

        def search(self, *_args, **_kwargs):
            return []

    audits = []
    result = collect_provider_batches(
        Client(),
        [NewsQueryBatch("A", (1,), ())],
        observed_at=datetime(2026, 10, 16, tzinfo=UTC),
        store=lambda *_: {},
        audit=audits.append,
    )
    assert result["requests"] == result["reusedRequests"] == 1
    assert result["sentRequests"] == result["blockedRequests"] == 0
    assert audits[0]["cursor_state"]["transport"] == {
        "attemptsSent": 0,
        "measured": True,
        "reuse_status": "cache_hit",
        "fetched_at_ms": 1000,
        "age_ms": 500,
    }
    assert "secret" not in str(audits)
