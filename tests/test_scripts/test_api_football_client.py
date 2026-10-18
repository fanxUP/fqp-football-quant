from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from scripts.api_football_client import ApiFootballClient


def test_client_defaults_to_free_plan_minute_rate_limit(monkeypatch):
    monkeypatch.delenv("API_FOOTBALL_MIN_INTERVAL_SECONDS", raising=False)
    client = ApiFootballClient(api_key="test-key")

    try:
        assert client._min_interval == 6.1
    finally:
        client.close()


def test_rate_limit_payload_fails_without_retry(monkeypatch):
    ledger = MagicMock(policy=SimpleNamespace(provider="api_football", day_reset_offset_seconds=0))
    ledger.mark_sent.return_value = SimpleNamespace(day_sent=1)
    client = ApiFootballClient(api_key="test-key", min_interval=0, max_retries=3, ledger=ledger)
    calls = 0

    def fake_get(path, **kwargs):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", path)
        return httpx.Response(
            200,
            request=request,
            json={
                "errors": {"rateLimit": "Too many requests"},
                "response": [],
            },
        )

    monkeypatch.setattr(client._client, "get", fake_get)

    try:
        with pytest.raises(RuntimeError, match="rate limit"):
            client._request("fixtures", {"date": "2026-07-22"})
        assert calls == 1
    finally:
        client.close()


def test_missing_quota_configuration_does_not_send(monkeypatch):
    from scripts.request_quota import QuotaUnavailable

    monkeypatch.delenv("FQP_REQUEST_QUOTA_CONFIG", raising=False)
    transport = MagicMock()
    client = ApiFootballClient(api_key="test-key", client=transport)
    with pytest.raises(QuotaUnavailable):
        client.get_fixtures(date="2026-10-16")
    transport.get.assert_not_called()
    assert client.call_count_today == 0


def test_legacy_counter_reset_does_not_reset_shared_account():
    ledger = MagicMock(policy=SimpleNamespace(provider="api_football", day_reset_offset_seconds=0))
    ledger.mark_sent.return_value = SimpleNamespace(day_sent=6)
    transport = httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"response": []}))
    )
    client = ApiFootballClient(api_key="test-key", client=transport, ledger=ledger, min_interval=0)
    client.get_fixtures()
    assert client.call_count_today == 1
    client.reset_call_count()
    assert client.call_count_today == 0
    ledger.provision.assert_not_called()
    assert ledger.mark_sent.call_count == 1
    client.close()
    assert not transport.is_closed
    transport.close()
