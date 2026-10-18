from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, Event
from uuid import uuid4

import httpx
import pytest
from redis import Redis

from scripts.request_quota import QuotaDenied, QuotaPolicy, QuotaUnavailable, RedisQuotaLedger
from scripts.request_reuse import RedisRequestReuse, ReusePolicy, ReuseUnavailable
from scripts.request_transport import GovernedJsonClient, ProviderRequestError

URL = "https://v3.football.api-sports.io/fixtures"
SECRET = "fixture-secret-credential"
PAYLOAD = {"errors": [], "response": [{"fixture": {"id": 10}}]}


@pytest.fixture
def redis():
    url = os.environ.get("FQP_QUOTA_TEST_REDIS_URL")
    if not url:
        pytest.fail("Dedicated isolated test Redis is required")
    client = Redis.from_url(url, decode_responses=True, socket_timeout=1)
    client.ping()
    yield client
    client.close()


def ledger_for(redis, *, provider="api_football", account=None, environment="test"):
    policy = QuotaPolicy(
        provider=provider,
        account_scope=account or "reuse-test-" + uuid4().hex,
        daily_limit=100,
        minute_limit=100,
        environment_limits=(("test", 50), ("dev", 50)),
    )
    ledger = RedisQuotaLedger(redis, policy, environment=environment)
    ledger.provision(daily_usage={"test": 0, "dev": 0}, minute_usage=0)
    return ledger


def reuse_for(redis, ledger=None, *, credential=SECRET, policy=None):
    ledger = ledger or ledger_for(redis)
    return RedisRequestReuse(
        redis,
        ledger,
        policy or ReusePolicy(permission_scope="research-v1", ttl_seconds=60, wait_ms=2000),
        credential=credential,
    )


def gate_for(redis, ledger=None, *, reuse=None, handler=None, provider="api_football"):
    ledger = ledger or ledger_for(redis, provider=provider)
    reuse = reuse or reuse_for(redis, ledger)
    handler = handler or (lambda request: httpx.Response(200, json=PAYLOAD))
    http = httpx.Client(transport=httpx.MockTransport(handler))
    gate = GovernedJsonClient(provider, SECRET, client=http, ledger=ledger, reuse=reuse)
    return gate, ledger, reuse, http


@pytest.mark.parametrize(
    "kwargs",
    [
        {"permission_scope": ""},
        {"permission_scope": "private key"},
        {"ttl_seconds": 0},
        {"ttl_seconds": 301},
        {"ttl_seconds": True},
        {"wait_ms": -1},
        {"wait_ms": 30001},
        {"wait_ms": False},
        {"max_payload_bytes": 0},
        {"max_payload_bytes": 1048577},
        {"max_payload_bytes": 1.1},
    ],
)
def test_policy_rejects_unsafe_or_unbounded_values(kwargs):
    with pytest.raises(ValueError):
        ReusePolicy(**({"permission_scope": "research-v1"} | kwargs))


def test_wire_equivalent_parameter_order_and_header_case_share_identity(redis):
    reuse = reuse_for(redis)
    left = reuse.key(URL, params={"team": 10, "page": 1}, headers={"Accept": "application/json"})
    right = reuse.key(
        URL, params={"page": "1", "team": "10"}, headers={"accept": "application/json"}
    )
    assert left == right
    assert SECRET not in left and "fixtures" not in left and "research" not in left


@pytest.mark.parametrize(
    "params",
    [
        {"page": 2},
        {"q": "Team A"},
        {"q": "team A"},
        {"from": "2026-10-01"},
        {"season": 2025},
        {"ids": [1, 2]},
        {"ids": [2, 1]},
        {"timezone": "UTC"},
    ],
)
def test_content_affecting_values_have_distinct_identity(redis, params):
    reuse = reuse_for(redis)
    assert reuse.key(URL, params=params) != reuse.key(URL)


def test_no_aggressive_text_list_or_header_normalization(redis):
    reuse = reuse_for(redis)
    assert reuse.key(URL, params={"q": "A  B"}) != reuse.key(URL, params={"q": "A B"})
    assert reuse.key(URL, params={"ids": [1, 2]}) != reuse.key(URL, params={"ids": [2, 1]})
    assert reuse.key(URL, headers={"Accept-Language": "en"}) != reuse.key(URL)
    assert reuse.key(URL.replace("fixtures", "injuries")) != reuse.key(URL)
    assert reuse.key(URL, headers={"Accept": "first", "accept": "second"}) != reuse.key(
        URL, headers={"Accept": "second", "accept": "first"}
    )


@pytest.mark.parametrize(
    "dimension", ["account", "environment", "permission", "credential", "quota", "reuse"]
)
def test_scope_isolation(redis, dimension):
    ledger = ledger_for(redis)
    policy = ReusePolicy(permission_scope="research-v1")
    first = reuse_for(redis, ledger, policy=policy)
    other = ledger
    credential = SECRET
    if dimension == "account":
        other = ledger_for(redis)
    elif dimension == "environment":
        other = RedisQuotaLedger(redis, ledger.policy, environment="dev")
    elif dimension == "permission":
        policy = replace(policy, permission_scope="research-v2")
    elif dimension == "credential":
        credential += "-rotated"
    elif dimension == "quota":
        other = RedisQuotaLedger(redis, replace(ledger.policy, minute_limit=90), environment="test")
    else:
        policy = replace(policy, ttl_seconds=30)
    assert first.key(URL) != reuse_for(redis, other, credential=credential, policy=policy).key(URL)


@pytest.mark.parametrize("location", ["params", "headers"])
def test_mismatched_credential_is_rejected_before_send(redis, location):
    gate, ledger, reuse, http = gate_for(redis)
    kwargs = {location: {"api-key" if location == "params" else "x-apisports-key": "wrong-secret"}}
    with http, pytest.raises(ReuseUnavailable, match="request_identity_invalid"):
        gate.get(URL, **kwargs)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 0


def test_cache_hit_has_original_time_no_quota_and_no_replayed_provider_headers(redis):
    gate, ledger, reuse, http = gate_for(redis)
    with http:
        assert gate.get(URL, params={"id": 10}) == PAYLOAD
        fetched = gate.last_request_meta["fetched_at_ms"]
        assert gate.last_request_meta["reuse_status"] == "fetched"
        assert gate.get(URL, params={"id": 10}) == PAYLOAD
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 1
    assert gate.last_request_meta["reuse_status"] == "cache_hit"
    assert gate.last_request_meta["attempts_sent"] == 0
    assert gate.last_request_meta["fetched_at_ms"] == fetched
    assert gate.last_request_meta["age_ms"] >= 0
    assert "http_status" not in gate.last_request_meta
    assert "remaining" not in gate.last_request_meta
    assert gate.last_request_meta["outcome"] == "completed"
    assert 0 < redis.pttl(reuse.key(URL, params={"id": 10})) <= 60000


def test_cached_mutable_response_does_not_pollute_other_callers(redis):
    gate, _, _, http = gate_for(redis)
    with http:
        gate.get(URL)["response"].clear()
        assert gate.get(URL) == PAYLOAD


def test_expiry_causes_one_new_send_and_new_observation_time(redis):
    gate, ledger, reuse, http = gate_for(redis)
    with http:
        gate.get(URL)
        first = gate.last_request_meta["fetched_at_ms"]
        redis.pexpire(reuse.key(URL), 1)
        deadline = time.monotonic() + 2
        while redis.exists(reuse.key(URL)) and time.monotonic() < deadline:
            time.sleep(0.002)
        gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 2
    assert gate.last_request_meta["fetched_at_ms"] > first


def test_exhausted_quota_can_reuse_but_permission_block_cannot(redis):
    gate, ledger, _, http = gate_for(redis)
    with http:
        gate.get(URL)
        state = json.loads(redis.get(ledger.key))
        state["day_ceiling"] = 1
        redis.set(ledger.key, json.dumps(state))
        assert gate.get(URL) == PAYLOAD
        state = json.loads(redis.get(ledger.key))
        state["blocked"] = "authentication_denied"
        redis.set(ledger.key, json.dumps(state))
        with pytest.raises(QuotaDenied, match="authentication_denied"):
            gate.get(URL)
    assert gate.total_sends == 1


@pytest.mark.parametrize(
    "fault", ["missing_ledger", "corrupt_ledger", "corrupt_cache", "expiry_missing", "store_down"]
)
def test_faults_do_not_bypass_cache_or_quota(redis, fault):
    gate, ledger, reuse, http = gate_for(redis)
    with http:
        gate.get(URL)
        key = reuse.key(URL)
        if fault == "missing_ledger":
            redis.delete(ledger.key)
        elif fault == "corrupt_ledger":
            redis.set(ledger.key, "invalid")
        elif fault == "corrupt_cache":
            redis.set(key, "invalid", px=60000)
        elif fault == "expiry_missing":
            redis.persist(key)
        else:
            reuse._client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.1)
        with pytest.raises((QuotaDenied, QuotaUnavailable, ReuseUnavailable)):
            gate.get(URL)
    assert gate.total_sends == 1


def test_two_clients_concurrently_share_single_send_and_separate_diagnostics(redis):
    ledger = ledger_for(redis)
    entered, release = Event(), Event()

    def handler(request):
        entered.set()
        assert release.wait(2)
        return httpx.Response(200, json=PAYLOAD)

    first, _, reuse, http1 = gate_for(redis, ledger, handler=handler)
    second, _, _, http2 = gate_for(redis, ledger)
    with http1, http2, ThreadPoolExecutor(2) as pool:
        left = pool.submit(first.get, URL)
        assert entered.wait(2)
        right = pool.submit(second.get, URL)
        time.sleep(0.06)
        release.set()
        assert left.result() == right.result() == PAYLOAD
    assert first.total_sends == 1 and second.total_sends == 0
    assert second.last_request_meta["reuse_status"] == "coalesced"
    assert ledger.snapshot()["day_sent"] == 1


def test_many_simultaneous_callers_share_only_one_send(redis):
    ledger = ledger_for(redis)
    barrier = Barrier(12)

    def request(_index):
        gate, _, _, http = gate_for(redis, ledger)
        with http:
            barrier.wait(timeout=4)
            assert gate.get(URL) == PAYLOAD
        return gate.total_sends

    with ThreadPoolExecutor(12) as pool:
        assert sum(pool.map(request, range(12))) == 1
    assert ledger.snapshot()["day_sent"] == 1


def _process_request(url, policy_dict, start, results):
    client = Redis.from_url(url, decode_responses=True)
    ledger = RedisQuotaLedger(client, QuotaPolicy(**policy_dict), environment="test")

    def handle(request):
        time.sleep(0.25)  # Keep the real owner in-flight while other processes arrive.
        return httpx.Response(200, json=PAYLOAD)

    gate, _, _, http = gate_for(client, ledger, handler=handle)
    with http:
        start.wait(5)
        gate.get(URL)
        results.put((gate.total_sends, gate.last_request_meta["reuse_status"]))
    client.close()


def test_independent_processes_share_singleflight(redis):
    from dataclasses import asdict

    ledger = ledger_for(redis)
    context = multiprocessing.get_context("spawn")
    start, results = context.Barrier(4), context.Queue()
    processes = [
        context.Process(
            target=_process_request,
            args=(os.environ["FQP_QUOTA_TEST_REDIS_URL"], asdict(ledger.policy), start, results),
        )
        for _ in range(4)
    ]
    for process in processes:
        process.start()
    sends = [results.get(timeout=15) for _ in processes]
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0
    assert sum(item[0] for item in sends) == ledger.snapshot()["day_sent"] == 1
    assert any(item[1] == "coalesced" for item in sends)


def test_terminal_error_is_shared_as_error_not_cached_empty_result(redis):
    def handler(request):
        return httpx.Response(503, json={"message": SECRET})

    gate, ledger, reuse, http = gate_for(redis, handler=handler)
    with http:
        with pytest.raises(ProviderRequestError, match="upstream_unavailable"):
            gate.get(URL)
        with pytest.raises(ReuseUnavailable, match="shared_request_failed"):
            gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 1
    assert SECRET not in redis.get(reuse.key(URL))


def test_running_owner_crash_never_auto_expires_or_steals(redis):
    gate, ledger, reuse, http = gate_for(redis)
    key = reuse.key(URL)
    redis.set(
        key,
        json.dumps(
            {
                "schema": "request-reuse/v1",
                "state": "running",
                "token": "dead-owner",
                "started_at_ms": 1,
            }
        ),
    )
    with http, pytest.raises(ReuseUnavailable, match="request_inflight_uncertain"):
        gate.get(URL)
    assert redis.pttl(key) == -1
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 0
    assert json.loads(redis.get(key))["token"] == "dead-owner"


def test_wait_is_bounded_and_does_not_take_over_live_owner(redis):
    ledger = ledger_for(redis)
    reuse = reuse_for(redis, ledger, policy=ReusePolicy(permission_scope="p1", wait_ms=20))
    gate, _, _, http = gate_for(redis, ledger, reuse=reuse)
    started = int(redis.time()[0] * 1000)
    key = reuse.key(URL)
    redis.set(
        key,
        json.dumps(
            {
                "schema": "request-reuse/v1",
                "state": "running",
                "token": "live-owner",
                "started_at_ms": started,
            }
        ),
    )
    before = time.monotonic()
    with http, pytest.raises(ReuseUnavailable, match="request_wait_timeout"):
        gate.get(URL)
    assert time.monotonic() - before < 1
    assert redis.pttl(key) == -1
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 0


@pytest.mark.parametrize("dimension", ["account", "environment", "credential"])
def test_injected_reuse_must_match_sending_identity(redis, dimension):
    ledger = ledger_for(redis)
    other = ledger_for(redis) if dimension == "account" else ledger
    if dimension == "environment":
        other = RedisQuotaLedger(redis, ledger.policy, environment="dev")
    reuse = reuse_for(
        redis, other, credential=SECRET + "-other" if dimension == "credential" else SECRET
    )
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: pytest.fail("No mismatched HTTP"))
    ) as http:
        with pytest.raises(ValueError, match="reuse identity mismatch"):
            GovernedJsonClient("api_football", SECRET, client=http, ledger=ledger, reuse=reuse)


@pytest.mark.parametrize(
    "payload", [{}, {"response": [SECRET], "errors": []}, {"response": ["x" * 1000], "errors": []}]
)
def test_non_reusable_response_owner_keeps_data_but_followers_do_not_send(redis, payload):
    ledger = ledger_for(redis)
    reuse = reuse_for(
        redis, ledger, policy=ReusePolicy(permission_scope="p1", max_payload_bytes=256)
    )
    gate, _, _, http = gate_for(
        redis, ledger, reuse=reuse, handler=lambda req: httpx.Response(200, json=payload)
    )
    with http:
        assert gate.get(URL) == payload
        assert gate.last_request_meta["reuse_status"] == "not_stored"
        with pytest.raises(ReuseUnavailable, match="shared_result_not_reusable"):
            gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 1
    assert SECRET not in redis.get(reuse.key(URL))


def test_publish_fenced_against_owner_replacement(redis):
    ledger = ledger_for(redis)
    reuse = reuse_for(redis, ledger)

    def handler(request):
        key = reuse.key(URL)
        entry = json.loads(redis.get(key))
        entry["token"] = "other-owner"
        redis.set(key, json.dumps(entry))
        return httpx.Response(200, json=PAYLOAD)

    gate, _, _, http = gate_for(redis, ledger, reuse=reuse, handler=handler)
    with http, pytest.raises(ReuseUnavailable, match="request_owner_lost"):
        gate.get(URL)
    assert json.loads(redis.get(reuse.key(URL)))["token"] == "other-owner"
    assert ledger.snapshot()["day_sent"] == 1


def test_configured_clients_only_enable_verified_retention_cache(redis, monkeypatch):
    ledger = ledger_for(redis)
    config = {
        "api_football": {
            "enabled": True,
            "runtime_verified": True,
            "credential_sha256": hashlib.sha256(SECRET.encode()).hexdigest(),
            "policy": __import__("dataclasses").asdict(ledger.policy),
            "reuse": {
                "enabled": True,
                "retention_verified": True,
                "permission_scope": "p1",
                "ttl_seconds": 60,
            },
        }
    }
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps(config))
    monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", os.environ["FQP_QUOTA_TEST_REDIS_URL"])
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=PAYLOAD))
    ) as http:
        gate = GovernedJsonClient("api_football", SECRET, client=http)
        try:
            gate.get(URL)
            gate.get(URL)
            assert gate.total_sends == 1
        finally:
            gate.close()


@pytest.mark.parametrize(
    "change",
    [
        {"retention_verified": False},
        {"permission_scope": ""},
        {"ttl_seconds": 1000},
        {"enabled": "true"},
    ],
)
def test_invalid_reuse_configuration_never_silently_sends(redis, monkeypatch, change):
    from dataclasses import asdict

    ledger = ledger_for(redis)
    reuse = {"enabled": True, "retention_verified": True, "permission_scope": "p1"} | change
    config = {
        "api_football": {
            "enabled": True,
            "runtime_verified": True,
            "credential_sha256": hashlib.sha256(SECRET.encode()).hexdigest(),
            "policy": asdict(ledger.policy),
            "reuse": reuse,
        }
    }
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps(config))
    monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", os.environ["FQP_QUOTA_TEST_REDIS_URL"])
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: pytest.fail("No HTTP on invalid config"))
    ) as http:
        gate = GovernedJsonClient("api_football", SECRET, client=http)
        try:
            with pytest.raises(QuotaUnavailable, match="reuse_configuration_unavailable"):
                gate.get(URL)
        finally:
            gate.close()


@pytest.mark.parametrize(
    "provider,url,payload",
    [
        ("api_football", URL, {"errors": [], "response": []}),
        ("newsapi", "https://newsapi.org/v2/everything", {"status": "ok", "articles": []}),
        ("gnews", "https://gnews.io/api/v4/search", {"articles": []}),
        (
            "guardian",
            "https://content.guardianapis.com/search",
            {"response": {"status": "ok", "results": []}},
        ),
    ],
)
def test_all_provider_success_envelopes_reuse_empty_results_without_reclassification(
    redis, provider, url, payload
):
    gate, ledger, _, http = gate_for(
        redis, provider=provider, handler=lambda req: httpx.Response(200, json=payload)
    )
    with http:
        assert gate.get(url) == gate.get(url) == payload
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 1
    assert gate.last_request_meta["reuse_status"] == "cache_hit"


def test_priority_isolated_from_normal_request_denial(redis):
    reuse = reuse_for(redis)
    assert reuse.key(URL) != reuse.key(URL, priority=True)


@pytest.mark.parametrize(
    "change",
    [
        {"state": "other"},
        {"fetched_at_ms": 9999999999999},
        {"body": "[]"},
        {"body": '{"response":NaN}'},
        {"schema": "old"},
    ],
)
def test_malformed_success_entry_never_returns_or_resends(redis, change):
    gate, _, reuse, http = gate_for(redis)
    with http:
        gate.get(URL)
        key = reuse.key(URL)
        entry = json.loads(redis.get(key)) | change
        redis.set(key, json.dumps(entry), px=60000)
        with pytest.raises(ReuseUnavailable, match="reuse_state_invalid"):
            gate.get(URL)
    assert gate.total_sends == 1


def test_shared_leader_retries_each_charged_but_follower_never_retries(redis):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("credential=" + SECRET)
        return httpx.Response(200, json=PAYLOAD)

    gate, ledger, reuse, http = gate_for(redis, handler=handle)
    gate._max_attempts = 2
    gate._wait = lambda _: None
    with http:
        assert gate.get(URL) == gate.get(URL) == PAYLOAD
    assert gate.total_sends == ledger.snapshot()["day_sent"] == calls == 2
    assert gate.last_request_meta["attempts_sent"] == 0


def test_permission_revoked_during_cache_read_is_checked_again(redis, monkeypatch):
    gate, ledger, reuse, http = gate_for(redis)
    with http:
        gate.get(URL)
        execute = reuse._execute

        def revoke(*args, **kwargs):
            result = execute(*args, **kwargs)
            state = json.loads(redis.get(ledger.key))
            state["blocked"] = "plan_denied"
            redis.set(ledger.key, json.dumps(state))
            return result

        monkeypatch.setattr(reuse, "_execute", revoke)
        with pytest.raises(QuotaDenied, match="plan_denied"):
            gate.get(URL)
    assert gate.total_sends == 1


def test_failed_publish_never_falls_back_to_another_http(redis):
    ledger = ledger_for(redis)
    reuse = reuse_for(redis, ledger)

    def handle(request):
        reuse._client = Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.1)
        return httpx.Response(200, json=PAYLOAD)

    gate, _, _, http = gate_for(redis, ledger, reuse=reuse, handler=handle)
    with http:
        with pytest.raises(ReuseUnavailable, match="reuse_store_unavailable"):
            gate.get(URL)
        with pytest.raises(ReuseUnavailable):
            gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 1
    assert redis.pttl(reuse.key(URL)) == -1


@pytest.mark.parametrize("provider", ["api_football", "newsapi", "gnews", "guardian"])
def test_existing_adapter_factories_share_cache_without_parser_rewrite(
    redis, monkeypatch, provider
):
    from dataclasses import asdict

    from scripts.api_football_client import ApiFootballClient
    from scripts.news_intelligence_clients import GNewsClient, GuardianClient, NewsApiClient

    ledger = ledger_for(redis, provider=provider)
    config = {
        provider: {
            "enabled": True,
            "runtime_verified": True,
            "credential_sha256": hashlib.sha256(SECRET.encode()).hexdigest(),
            "policy": asdict(ledger.policy),
            "reuse": {"enabled": True, "retention_verified": True, "permission_scope": "p1"},
        }
    }
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps(config))
    monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", os.environ["FQP_QUOTA_TEST_REDIS_URL"])
    payloads = {
        "api_football": {"errors": [], "response": []},
        "newsapi": {"status": "ok", "articles": []},
        "gnews": {"articles": []},
        "guardian": {"response": {"status": "ok", "results": []}},
    }
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=payloads[provider]))
    ) as http:
        classes = {
            "api_football": ApiFootballClient,
            "newsapi": NewsApiClient,
            "gnews": GNewsClient,
            "guardian": GuardianClient,
        }
        client = classes[provider](SECRET, client=http)
        try:
            request = (
                (lambda: client.get_fixtures(fixture_id=10))
                if provider == "api_football"
                else (lambda: client.search("Team"))
            )
            assert request() == request() == []
            assert client._transport.total_sends == 1
            assert client._transport.last_request_meta["reuse_status"] == "cache_hit"
        finally:
            client.close()


@pytest.mark.parametrize("reuse_config", [None, {"enabled": False}])
def test_absent_or_disabled_reuse_preserves_governed_send_only(redis, monkeypatch, reuse_config):
    from dataclasses import asdict

    ledger = ledger_for(redis)
    entry = {
        "enabled": True,
        "runtime_verified": True,
        "credential_sha256": hashlib.sha256(SECRET.encode()).hexdigest(),
        "policy": asdict(ledger.policy),
    }
    if reuse_config is not None:
        entry["reuse"] = reuse_config
    monkeypatch.setenv("FQP_REQUEST_QUOTA_CONFIG", json.dumps({"api_football": entry}))
    monkeypatch.setenv("FQP_REQUEST_QUOTA_ENVIRONMENT", "test")
    monkeypatch.setenv("REDIS_URL", os.environ["FQP_QUOTA_TEST_REDIS_URL"])
    with httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=PAYLOAD))
    ) as http:
        gate = GovernedJsonClient("api_football", SECRET, client=http)
        try:
            gate.get(URL)
            gate.get(URL)
            assert gate.total_sends == ledger.snapshot()["day_sent"] == 2
            assert "reuse_status" not in gate.last_request_meta
        finally:
            gate.close()


@pytest.mark.parametrize("dimension", ["headers", "params", "cookies"])
def test_http_client_defaults_are_part_of_actual_request_identity(redis, dimension):
    gate, ledger, _, http = gate_for(redis)
    with http:
        gate.get(URL)
        if dimension == "headers":
            http.headers["Accept-Language"] = "zh"
        elif dimension == "params":
            http.params = {"season": "2025"}
        else:
            http.cookies.set("content-edition", "other")
        gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 2


def test_implicit_auth_flow_cannot_reuse_under_incomplete_identity(redis):
    gate, ledger, _, http = gate_for(redis)
    http.auth = ("username", "private-password")
    with http, pytest.raises(ReuseUnavailable, match="request_identity_invalid"):
        gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 0


def test_bound_coordinator_cannot_silently_switch_http_client(redis):
    gate, ledger, reuse, http = gate_for(redis)
    with http, httpx.Client() as other:
        with pytest.raises(ReuseUnavailable, match="request_identity_invalid"):
            GovernedJsonClient("api_football", SECRET, client=other, ledger=ledger, reuse=reuse)
    assert gate.total_sends == 0


def test_injected_reuse_checks_same_ledger_instance_not_only_policy(redis):
    ledger = ledger_for(redis)
    other = RedisQuotaLedger(redis, ledger.policy, environment="test")
    reuse = reuse_for(redis, other)
    with httpx.Client() as http, pytest.raises(ValueError, match="reuse identity mismatch"):
        GovernedJsonClient("api_football", SECRET, client=http, ledger=ledger, reuse=reuse)


def test_mutating_http_hooks_are_rejected_before_quota_or_send(redis):
    gate, ledger, _, http = gate_for(redis)
    http.event_hooks["request"].append(lambda request: request.headers.update({"edition": "other"}))
    with http, pytest.raises(ReuseUnavailable, match="request_identity_invalid"):
        gate.get(URL)
    assert gate.total_sends == ledger.snapshot()["day_sent"] == 0


def test_response_cookie_change_is_not_published_under_old_identity(redis):
    ledger = ledger_for(redis)
    first, _, _, http1 = gate_for(
        redis,
        ledger,
        handler=lambda req: httpx.Response(
            200, json=PAYLOAD, headers={"set-cookie": "edition=private"}
        ),
    )
    second, _, _, http2 = gate_for(redis, ledger)
    with http1, http2:
        assert first.get(URL) == PAYLOAD
        assert first.last_request_meta["reuse_status"] == "not_stored"
        with pytest.raises(ReuseUnavailable, match="shared_result_not_reusable"):
            second.get(URL)
    assert first.total_sends == 1 and second.total_sends == 0
