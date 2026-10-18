from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from redis import Redis

from scripts.request_quota import QuotaDenied, QuotaPolicy, QuotaUnavailable, RedisQuotaLedger
from scripts.request_transport import GovernedJsonClient, ProviderRequestError

URLS = {
    "api_football": "https://v3.football.api-sports.io/fixtures",
    "newsapi": "https://newsapi.org/v2/everything",
    "gnews": "https://gnews.io/api/v4/search",
    "guardian": "https://content.guardianapis.com/search",
}


class Ledger:
    def __init__(self, provider="api_football"):
        self.policy = SimpleNamespace(provider=provider, day_reset_offset_seconds=0)
        self.events = []
        self.feedback = []
        self.denial = None

    def reserve(self, **kwargs):
        self.events.append("reserve")
        if self.denial:
            raise self.denial
        return str(len(self.events))

    def mark_sent(self, token):
        self.events.append("sent:" + token)
        return SimpleNamespace(day_sent=len(self.events))

    def cancel(self, token):
        self.events.append("cancel:" + token)

    def apply_feedback(self, receipt, **kwargs):
        self.feedback.append(kwargs)


def make(provider="api_football", *, ledger=None, replies=None, **kwargs):
    ledger = ledger or Ledger(provider)
    calls = []
    replies = iter(replies or [httpx.Response(200, json={"response": []})])

    def handle(request):
        calls.append(request)
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = httpx.Client(transport=httpx.MockTransport(handle))
    gate = GovernedJsonClient(
        provider, "test-secret", client=client, ledger=ledger, wait=lambda _seconds: None, **kwargs
    )
    return gate, ledger, calls


@pytest.mark.parametrize("provider", URLS)
def test_all_providers_reserve_then_consume_once(provider):
    gate, ledger, calls = make(provider)
    assert gate.get(URLS[provider], params={"q": "Team"}) == {"response": []}
    assert ledger.events == ["reserve", "sent:1"]
    assert len(calls) == gate.total_sends == gate.last_request_meta["attempts_sent"] == 1
    assert gate.last_request_meta["outcome"] == "completed"


@pytest.mark.parametrize(
    "failure", [QuotaDenied("day_exhausted"), QuotaUnavailable("quota_store_unavailable")]
)
def test_quota_denial_never_sends(failure):
    gate, ledger, calls = make()
    ledger.denial = failure
    with pytest.raises((QuotaDenied, QuotaUnavailable)):
        gate.get(URLS["api_football"])
    assert calls == []
    assert gate.last_request_meta["attempts_sent"] == 0
    assert gate.last_request_meta["outcome"] == "blocked"


def test_failed_send_consumption_releases_only_unsent_permit():
    gate, ledger, calls = make()

    def deny(_token):
        raise QuotaDenied("minimum_interval", 1000)

    ledger.mark_sent = deny
    with pytest.raises(QuotaDenied):
        gate.get(URLS["api_football"])
    assert ledger.events == ["reserve", "cancel:1"]
    assert not calls


@pytest.mark.parametrize(
    "reply", [httpx.ReadTimeout("contains test-secret"), httpx.Response(503, json={})]
)
def test_each_retry_gets_new_permit_and_timeout_is_not_refunded(reply):
    gate, ledger, calls = make(replies=[reply, httpx.Response(200, json={})], max_attempts=2)
    assert gate.get(URLS["api_football"]) == {}
    assert len(calls) == 2
    assert ledger.events == ["reserve", "sent:1", "reserve", "sent:3"]
    assert gate.last_request_meta["attempts_sent"] == 2


@pytest.mark.parametrize(
    "status,reason,denied",
    [
        (401, "authentication_denied", "authentication_denied"),
        (403, "plan_denied", "plan_denied"),
        (429, "rate_limited", None),
        (400, "http_rejected", None),
        (302, "redirect_denied", None),
        (304, "http_rejected", None),
    ],
)
def test_permanent_http_failures_do_not_retry(status, reason, denied):
    gate, ledger, calls = make(
        replies=[
            httpx.Response(
                status, headers={"Location": "https://evil.test/?apikey=test-secret"}, json={}
            )
        ],
        max_attempts=3,
    )
    with pytest.raises(ProviderRequestError) as caught:
        gate.get(URLS["api_football"])
    assert caught.value.reason == reason
    assert len(calls) == 1
    assert ledger.feedback[0]["denied"] == denied
    assert "test-secret" not in str(caught.value)
    if status == 429:
        assert ledger.feedback[0]["retry_after_ms"] >= 60000


@pytest.mark.parametrize(
    "provider,payload,reason",
    [
        ("api_football", {"errors": {"rateLimit": "Too many requests"}}, "rate_limited"),
        ("api_football", {"errors": {"requests": "Daily limit reached"}}, "daily_exhausted"),
        ("api_football", {"errors": {"token": "Invalid key"}}, "authentication_denied"),
        ("api_football", {"errors": {"subscription": "Plan required"}}, "plan_denied"),
        ("api_football", {"errors": {"fixture": "Invalid fixture"}}, "provider_rejected"),
        ("newsapi", {"status": "error", "code": "apiKeyExhausted"}, "daily_exhausted"),
        ("newsapi", {"status": "error", "code": "apiKeyInvalid"}, "authentication_denied"),
        ("newsapi", {"status": "error", "code": "rateLimited"}, "rate_limited"),
        ("newsapi", {"status": "error", "code": "parameterInvalid"}, "provider_rejected"),
        ("gnews", {"errors": ["Invalid query"]}, "provider_rejected"),
        (
            "guardian",
            {"response": {"status": "error", "message": "Invalid query"}},
            "provider_rejected",
        ),
    ],
)
def test_error_envelope_never_becomes_empty_success(provider, payload, reason):
    gate, ledger, calls = make(
        provider, replies=[httpx.Response(200, json=payload)], max_attempts=3
    )
    with pytest.raises(ProviderRequestError) as caught:
        gate.get(URLS[provider])
    assert caught.value.reason == reason
    assert len(calls) == 1
    assert gate.last_request_meta["outcome"] == "failed"


def test_gnews_daily_403_is_window_exhaustion_not_permanent_plan_block():
    body = {
        "errors": [
            "You have reached your request limit for today, the next reset will be tomorrow at midnight UTC."
        ]
    }
    gate, ledger, calls = make("gnews", replies=[httpx.Response(403, json=body)])
    with pytest.raises(ProviderRequestError) as caught:
        gate.get(URLS["gnews"])
    assert caught.value.reason == "daily_exhausted"
    assert ledger.feedback[0]["daily_remaining"] == 0
    assert ledger.feedback[0]["denied"] is None
    assert len(calls) == 1


@pytest.mark.parametrize(
    "value,expected",
    [("0", 0), ("7", 7), ("-1", None), ("bad", None), ("1.5", None), ("1000001", None)],
)
def test_api_football_remaining_headers_are_bounded(value, expected):
    gate, ledger, _calls = make(
        replies=[
            httpx.Response(
                200,
                headers={"X-RateLimit-Requests-Remaining": value, "X-RateLimit-Remaining": "3"},
                json={},
            )
        ]
    )
    gate.get(URLS["api_football"])
    assert ledger.feedback[0]["daily_remaining"] == expected
    assert ledger.feedback[0]["minute_remaining"] == 3


@pytest.mark.parametrize("value", ["5", "http-date"])
def test_retry_after_shared_without_sleeping_away_provider_block(value):
    now = datetime(2026, 10, 16, 1, 2, tzinfo=UTC)
    header = (
        format_datetime(now + timedelta(seconds=5), usegmt=True) if value == "http-date" else value
    )
    gate, ledger, calls = make(
        replies=[
            httpx.Response(
                429,
                headers={"Date": format_datetime(now, usegmt=True), "Retry-After": header},
                json={},
            )
        ],
        max_attempts=3,
    )
    with pytest.raises(ProviderRequestError):
        gate.get(URLS["api_football"])
    assert ledger.feedback[0]["retry_after_ms"] == 5000
    assert len(calls) == 1


@pytest.mark.parametrize("body", [b"not json", b"[]", b"null"])
def test_malformed_response_is_charged_not_retried(body):
    gate, ledger, calls = make(replies=[httpx.Response(200, content=body)], max_attempts=3)
    with pytest.raises(ProviderRequestError, match="invalid_response"):
        gate.get(URLS["api_football"])
    assert len(calls) == 1
    assert ledger.events == ["reserve", "sent:1"]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.test/fixtures",
        "http://v3.football.api-sports.io/fixtures",
        "https://v3.football.api-sports.io/fixtures?apikey=test-secret",
        "https://test-secret@v3.football.api-sports.io/fixtures",
    ],
)
def test_url_cannot_move_credentials_to_other_origin(url):
    gate, ledger, calls = make()
    with pytest.raises(ProviderRequestError, match="endpoint_denied"):
        gate.get(url)
    assert not calls and not ledger.events


def test_terminal_timeout_exception_and_metadata_are_secret_free(capsys):
    gate, ledger, calls = make(
        "gnews", replies=[httpx.ReadTimeout("https://gnews.io/?apikey=test-secret")]
    )
    with pytest.raises(ProviderRequestError) as caught:
        gate.get(URLS["gnews"])
    assert (
        "test-secret"
        not in str(caught.value) + json.dumps(gate.last_request_meta) + capsys.readouterr().out
    )
    assert caught.value.__suppress_context__


def test_httpx_info_logging_redacts_query_credentials(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="httpx")
    gate, _ledger, _calls = make("gnews")
    gate.get(URLS["gnews"], params={"q": "Team", "apikey": "test-secret"})
    assert "HTTP Request" in caplog.text
    assert "test-secret" not in caplog.text


def test_httpx_debug_headers_do_not_expose_api_keys(caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    gate, _ledger, _calls = make("newsapi")
    gate.get(URLS["newsapi"], headers={"X-Api-Key": "test-secret"})
    assert "test-secret" not in caplog.text


def test_feedback_failure_never_retries_or_returns_unreconciled_success():
    gate, ledger, calls = make(max_attempts=3)

    def fail(*args, **kwargs):
        raise QuotaUnavailable("quota_store_unavailable")

    ledger.apply_feedback = fail
    with pytest.raises(QuotaUnavailable):
        gate.get(URLS["api_football"])
    assert len(calls) == 1


@pytest.mark.parametrize("max_attempts", [0, 4, True])
def test_retry_count_is_bounded(max_attempts):
    with pytest.raises(ValueError):
        make(max_attempts=max_attempts)


def test_mismatched_injected_account_provider_rejected():
    with pytest.raises(ValueError):
        make("gnews", ledger=Ledger("newsapi"))


@pytest.mark.parametrize("key", ["", " ", None])
def test_missing_credential_is_rejected(key):
    with pytest.raises(ValueError):
        GovernedJsonClient("gnews", key, client=object(), ledger=Ledger("gnews"))


def test_redirects_are_disabled_even_when_http_client_defaults_to_follow():
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"Location": "https://evil.test/"}, json={})

    client = httpx.Client(transport=httpx.MockTransport(handle), follow_redirects=True)
    gate = GovernedJsonClient("guardian", "test-secret", client=client, ledger=Ledger("guardian"))
    with pytest.raises(ProviderRequestError, match="redirect_denied"):
        gate.get(URLS["guardian"], params={"api-key": "test-secret"})
    assert len(calls) == 1
    client.close()


@pytest.mark.parametrize(
    "client_name,provider,payload",
    [
        ("NewsApiClient", "newsapi", {"articles": []}),
        ("GNewsClient", "gnews", {"articles": []}),
        ("GuardianClient", "guardian", {"response": {"results": []}}),
    ],
)
def test_news_adapter_retry_metadata_counts_real_attempts(client_name, provider, payload):
    from scripts import news_intelligence_clients as news

    ledger = Ledger(provider)
    replies = iter([httpx.ReadTimeout("test-secret"), httpx.Response(200, json=payload)])

    def handle(_request):
        reply = next(replies)
        if isinstance(reply, Exception):
            raise reply
        return reply

    http = httpx.Client(transport=httpx.MockTransport(handle))
    client = getattr(news, client_name)("test-secret", client=http, ledger=ledger, max_attempts=2)
    client._transport._wait = lambda _: None
    assert client.search("Team") == []
    assert client.total_sends == client.last_request_meta["attempts_sent"] == 2
    assert ledger.events == ["reserve", "sent:1", "reserve", "sent:3"]
    client.close()
    http.close()


@pytest.fixture
def real_ledger():
    url = os.getenv("FQP_QUOTA_TEST_REDIS_URL")
    if not url:
        pytest.skip("explicit isolated Redis URL required")
    redis = Redis.from_url(
        url, decode_responses=True, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    policy = QuotaPolicy("api_football", "fixture-" + uuid4().hex, 30, 30, (("test", 30),))
    ledger = RedisQuotaLedger(redis, policy, environment="test")
    ledger.provision(daily_usage={"test": 0}, minute_usage=0)
    yield ledger
    redis.delete(ledger.key)
    redis.close()


def test_real_ledger_counts_each_timeout_attempt(real_ledger):
    gate, _, calls = make(
        ledger=real_ledger,
        replies=[httpx.ReadTimeout("timeout"), httpx.Response(200, json={})],
        max_attempts=2,
    )
    gate.get(URLS["api_football"])
    state = real_ledger.snapshot()
    assert len(calls) == state["day_used"] == state["day_sent"] == 2


def test_real_daily_feedback_stops_second_client(real_ledger):
    first, _, calls = make(
        ledger=real_ledger,
        replies=[httpx.Response(200, headers={"X-RateLimit-Requests-Remaining": "0"}, json={})],
    )
    first.get(URLS["api_football"])
    second, _, second_calls = make(ledger=real_ledger)
    with pytest.raises(QuotaDenied):
        second.get(URLS["api_football"])
    assert len(calls) == 1 and not second_calls


def test_actual_transport_concurrency_respects_one_account(real_ledger):
    # 30 daily grants shared across 40 independent transport instances.
    def request(_):
        gate, _, calls = make(ledger=real_ledger)
        try:
            gate.get(URLS["api_football"])
        except QuotaDenied:
            pass
        return len(calls)

    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(request, range(40)))
    assert sum(counts) == real_ledger.snapshot()["day_sent"] == 30


def test_missing_ledger_never_opens_zero_balance(real_ledger):
    real_ledger._client.delete(real_ledger.key)
    gate, _, calls = make(ledger=real_ledger)
    with pytest.raises(QuotaDenied):
        gate.get(URLS["api_football"])
    assert not calls
    assert not real_ledger._client.exists(real_ledger.key)


def config(monkeypatch, real_ledger):
    from dataclasses import asdict

    entry = {
        "enabled": True,
        "runtime_verified": True,
        "credential_sha256": hashlib.sha256(b"test-secret").hexdigest(),
        "policy": asdict(real_ledger.policy),
    }
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps({"api_football": entry}))
    monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", os.environ["FQP_QUOTA_TEST_REDIS_URL"])
    return entry


def test_explicit_config_reuses_provisioned_ledger(monkeypatch, real_ledger):
    config(monkeypatch, real_ledger)
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
    gate = GovernedJsonClient("api_football", "test-secret", client=client)
    gate.get(URLS["api_football"])
    assert real_ledger.snapshot()["day_sent"] == 1
    gate.close()


def test_configured_redis_outage_fails_closed_without_http(monkeypatch, real_ledger):
    config(monkeypatch, real_ledger)
    monkeypatch.setenv("REDIS_URL", "redis://test-secret@127.0.0.1:1/0")
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r)))
    gate = GovernedJsonClient("api_football", "test-secret", client=client)
    with pytest.raises(QuotaUnavailable) as caught:
        gate.get(URLS["api_football"])
    assert not calls and "test-secret" not in str(caught.value)
    gate.close()
    client.close()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "malformed",
        "disabled",
        "unverified",
        "credential",
        "environment",
        "redis",
        "provider",
    ],
)
def test_configuration_faults_never_send(monkeypatch, real_ledger, fault):
    entry = config(monkeypatch, real_ledger)
    if fault == "disabled":
        entry["enabled"] = False
    if fault == "unverified":
        entry["runtime_verified"] = False
    if fault == "credential":
        entry["credential_sha256"] = "0" * 64
    if fault == "provider":
        entry["policy"]["provider"] = "newsapi"
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps({"api_football": entry}))
    if fault == "missing":
        monkeypatch.delenv("FQP_REQUEST_QUOTA_CONFIG")
    if fault == "malformed":
        monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", "{test-secret")
    if fault == "environment":
        monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "prod")
    if fault == "redis":
        monkeypatch.delenv("REDIS_URL")
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r)))
    gate = GovernedJsonClient("api_football", "test-secret", client=client)
    with pytest.raises(QuotaUnavailable) as caught:
        gate.get(URLS["api_football"])
    assert not calls and "test-secret" not in str(caught.value)
