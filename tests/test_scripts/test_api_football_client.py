from __future__ import annotations

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
    client = ApiFootballClient(api_key="test-key", min_interval=0, max_retries=3)
    calls = 0

    def fake_get(path, params=None):
        nonlocal calls
        calls += 1
        request = httpx.Request("GET", f"https://example.test/{path}")
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
