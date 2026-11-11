"""Shared quota-governed JSON requests for existing football/news adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from scripts.request_quota import QuotaDenied, QuotaPolicy, QuotaUnavailable, RedisQuotaLedger
from scripts.request_reuse import RedisRequestReuse, ReusePolicy, ReuseUnavailable

_ENDPOINTS = {
    "api_football": "https://v3.football.api-sports.io/",
    "newsapi": "https://newsapi.org/v2/everything",
    "gnews": "https://gnews.io/api/v4/search",
    "guardian": "https://content.guardianapis.com/search",
}
_TRANSIENT_HTTP = {408, 499, 500, 502, 503, 504}


class _RedactQueryCredentials(logging.Filter):
    """HTTPX logs URLs at INFO, including credentials required by some providers."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = re.sub(
            r"([?&](?:apikey|api-key|api_key|key|token)=)[^&\s\"']+",
            r"\1REDACTED",
            record.getMessage(),
            flags=re.IGNORECASE,
        )
        record.args = ()
        return True


logging.getLogger("httpx").addFilter(_RedactQueryCredentials())


class ProviderRequestError(RuntimeError):
    """Bounded reason only: raw URLs, error messages and credentials stay private."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _configured_ledger(provider: str, api_key: str) -> tuple[RedisQuotaLedger, Redis]:
    """Explicit trusted operator configuration; never opens or repairs a ledger."""
    try:
        config = json.loads(os.environ["FQP_REQUEST_QUOTA_CONFIG"])
        entry = config[provider]
        if entry["enabled"] is not True or entry["runtime_verified"] is not True:
            raise ValueError
        expected = entry["credential_sha256"]
        actual = hashlib.sha256(api_key.encode()).hexdigest()
        if not isinstance(expected, str) or not hmac.compare_digest(expected, actual):
            raise ValueError
        policy = QuotaPolicy(**entry["policy"])
        if policy.provider != provider:
            raise ValueError
        environment = os.environ["FQP_REQUEST_QUOTA_ENVIRONMENT"]
        if environment not in dict(policy.environment_limits):
            raise ValueError
        url = os.environ["REDIS_URL"]
        if not url:
            raise ValueError
        redis = Redis.from_url(
            url,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            max_connections=8,
            retry=Retry(NoBackoff(), 0),
            retry_on_timeout=False,
        )
        return RedisQuotaLedger(redis, policy, environment=environment), redis
    except KeyError, TypeError, ValueError, AttributeError:
        raise QuotaUnavailable("quota_configuration_unavailable") from None


def _remaining(value: str | None) -> int | None:
    if value is not None and re.fullmatch(r"\d{1,7}", value):
        count = int(value)
        if count <= 1_000_000:
            return count
    return None


def _configured_reuse(
    provider: str, api_key: str, ledger: RedisQuotaLedger, client: Redis
) -> RedisRequestReuse | None:
    """Reuse needs separate explicit retention/permission approval; absent means off."""
    try:
        entry = json.loads(os.environ["FQP_REQUEST_QUOTA_CONFIG"])[provider]
        reuse = entry.get("reuse")
        if reuse is None:
            return None
        if reuse["enabled"] is False:
            return None
        if reuse["enabled"] is not True or reuse["retention_verified"] is not True:
            raise ValueError
        policy = ReusePolicy(
            **{k: v for k, v in reuse.items() if k not in ("enabled", "retention_verified")}
        )
        return RedisRequestReuse(client, ledger, policy, credential=api_key)
    except KeyError, ValueError, TypeError, AttributeError:
        raise QuotaUnavailable("reuse_configuration_unavailable") from None


def _retry_after(headers: httpx.Headers) -> int:
    value = headers.get("retry-after", "")
    if value.isascii() and value.isdigit():
        significant = value.lstrip("0") or "0"
        return 604_800_000 if len(significant) > 9 else min(int(significant) * 1000, 604_800_000)
    try:
        target = parsedate_to_datetime(value)
        origin = parsedate_to_datetime(headers["date"]) if "date" in headers else datetime.now(UTC)
        if target.tzinfo is None or origin.tzinfo is None:
            return 0
        return min(max(0, math.ceil((target - origin).total_seconds() * 1000)), 604_800_000)
    except ValueError, TypeError, OverflowError:
        return 0


def _body_reason(provider: str, payload: dict[str, Any], *, utc_reset: bool) -> str | None:
    if provider == "api_football":
        errors = payload.get("errors")
        if errors:
            keys = {str(key).lower() for key in errors} if isinstance(errors, dict) else set()
            if "token" in keys:
                return "authentication_denied"
            if "subscription" in keys:
                return "plan_denied"
            if "requests" in keys:
                return "daily_exhausted"
            if "ratelimit" in keys:
                return "rate_limited"
            return "provider_rejected"
    elif provider == "newsapi" and payload.get("status") == "error":
        code = payload.get("code")
        if code in ("apiKeyDisabled", "apiKeyInvalid", "apiKeyMissing"):
            return "authentication_denied"
        if code == "apiKeyExhausted":
            return "daily_exhausted"
        if code == "rateLimited":
            return "rate_limited"
        return "provider_rejected"
    elif provider == "gnews" and payload.get("errors"):
        errors = payload["errors"]
        if (
            utc_reset
            and isinstance(errors, list)
            and any(
                isinstance(error, str)
                and "request limit for today" in error.lower()
                and "midnight utc" in error.lower()
                for error in errors
            )
        ):
            return "daily_exhausted"
        return "provider_rejected"
    elif provider == "guardian":
        body = payload.get("response")
        if isinstance(body, dict) and body.get("status") == "error":
            return "provider_rejected"
    return None


class GovernedJsonClient:
    """Per-client diagnostics; quota coordination belongs to the shared Redis ledger.

    Injection is for trusted internal callers/tests, never a public bypass. Instances
    carry last-request metadata and should be owned by one sequential job.
    """

    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        client: Any,
        ledger: RedisQuotaLedger | None = None,
        reuse: RedisRequestReuse | None = None,
        max_attempts: int = 1,
        min_interval_seconds: float = 0,
        wait: Callable[[float], None] = time.sleep,
    ) -> None:
        if provider not in _ENDPOINTS:
            raise ValueError("unsupported governed provider")
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("provider credential required")
        if ledger is not None and ledger.policy.provider != provider:
            raise ValueError("quota provider mismatch")
        if reuse is not None and (ledger is None or not reuse.matches(ledger, api_key)):
            raise ValueError("reuse identity mismatch")
        if reuse is not None:
            reuse.bind_transport(client)
        if type(max_attempts) is not int or not 1 <= max_attempts <= 3:
            raise ValueError("max_attempts must be 1..3")
        if not math.isfinite(min_interval_seconds) or not 0 <= min_interval_seconds <= 60:
            raise ValueError("minimum interval must be 0..60 seconds")
        self.provider = provider
        self._api_key = api_key
        self._client = client
        self._ledger = ledger
        self._reuse = reuse
        self._reuse_configured = ledger is not None
        self._owned_redis: Redis | None = None
        self._max_attempts = max_attempts
        self._interval = min_interval_seconds
        self._wait = wait
        self._last_sent = 0.0
        self.total_sends = 0
        self.last_request_meta: dict[str, Any] = {}

    def _feedback(self, response: httpx.Response, payload: dict[str, Any]) -> str | None:
        assert self._ledger is not None
        status = response.status_code
        body = _body_reason(
            self.provider, payload, utc_reset=self._ledger.policy.day_reset_offset_seconds == 0
        )
        reason = body
        if status == 401:
            reason = "authentication_denied"
        elif status == 403 and body != "daily_exhausted":
            reason = "plan_denied"
        elif status == 429:
            reason = "rate_limited" if body != "daily_exhausted" else body
        elif 300 <= status < 400:
            reason = "http_rejected" if status == 304 else "redirect_denied"
        elif not 200 <= status < 300 and reason is None:
            reason = "upstream_unavailable" if status in _TRANSIENT_HTTP else "http_rejected"
        return reason

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        priority: bool = False,
    ) -> dict[str, Any]:
        self.last_request_meta = {
            "provider": self.provider,
            "attempts_sent": 0,
            "outcome": "blocked",
        }
        parsed = urlsplit(url)
        expected = _ENDPOINTS[self.provider]
        valid = url.startswith(expected) if self.provider == "api_football" else url == expected
        if not valid or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ProviderRequestError("endpoint_denied")
        if self._ledger is None:
            self._ledger, self._owned_redis = _configured_ledger(self.provider, self._api_key)
        if not self._reuse_configured:
            assert self._owned_redis is not None
            self._reuse = _configured_reuse(
                self.provider, self._api_key, self._ledger, self._owned_redis
            )
            if self._reuse is not None:
                self._reuse.bind_transport(self._client)
            self._reuse_configured = True
        if self._reuse is not None:
            try:
                return self._reuse.get(
                    url,
                    headers=headers,
                    params=params,
                    priority=priority,
                    load=lambda: self._send(url, headers=headers, params=params, priority=priority),
                    meta=self.last_request_meta,
                )
            except ReuseUnavailable, QuotaDenied, QuotaUnavailable:
                self.last_request_meta.update(
                    reuse_status="unavailable",
                    outcome="failed" if self.last_request_meta["attempts_sent"] else "blocked",
                )
                raise
        return self._send(url, headers=headers, params=params, priority=priority)

    def _send(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        priority: bool,
    ) -> dict[str, Any]:
        assert self._ledger is not None
        for attempt in range(self._max_attempts):
            if attempt:
                self._wait(2**attempt)
            delay = self._interval - (time.monotonic() - self._last_sent)
            if delay > 0:
                self._wait(delay)
            try:
                token = self._ledger.reserve(priority=priority)
                try:
                    receipt = self._ledger.mark_sent(token)
                except QuotaDenied, QuotaUnavailable:
                    try:
                        self._ledger.cancel(token)
                    except QuotaDenied, QuotaUnavailable:
                        pass  # Unknown consumption remains charged; never retry the send.
                    raise
            except QuotaDenied, QuotaUnavailable:
                self.last_request_meta["outcome"] = "blocked"
                raise
            self.total_sends += 1
            self.last_request_meta["attempts_sent"] += 1
            self.last_request_meta["quota_day_sent"] = receipt.day_sent
            self.last_request_meta["outcome"] = "failed"
            self._last_sent = time.monotonic()
            try:
                # Consume immediately before this one transport attempt. Redirects are
                # never followed with query-string credentials or an unmetered request.
                response = self._client.get(
                    url, headers=headers, params=params, follow_redirects=False
                )
            except httpx.HTTPError:
                if attempt + 1 < self._max_attempts:
                    continue
                raise ProviderRequestError("transport_failed") from None
            except ValueError:
                raise ProviderRequestError("request_invalid") from None
            self.last_request_meta["http_status"] = response.status_code
            try:
                raw = response.json()
            except ValueError:
                raw = None
            payload = raw if isinstance(raw, dict) else {}
            reason = self._feedback(response, payload)
            daily = minute = None
            if self.provider == "api_football":
                daily = _remaining(response.headers.get("x-ratelimit-requests-remaining"))
                minute = _remaining(response.headers.get("x-ratelimit-remaining"))
            if reason == "daily_exhausted":
                daily = 0
            if reason == "rate_limited":
                minute = 0
            cooldown = _retry_after(response.headers)
            if reason == "rate_limited" and not cooldown:
                cooldown = 60_000
            try:
                self._ledger.apply_feedback(
                    receipt,
                    daily_remaining=daily,
                    minute_remaining=minute,
                    retry_after_ms=cooldown,
                    denied=reason if reason in ("authentication_denied", "plan_denied") else None,
                )
            except QuotaDenied, QuotaUnavailable:
                self.last_request_meta["reason"] = "feedback_unavailable"
                raise
            self.last_request_meta.update(remaining=daily, minute_remaining=minute)
            if reason:
                self.last_request_meta["reason"] = reason
                if (
                    reason == "upstream_unavailable"
                    and not cooldown
                    and attempt + 1 < self._max_attempts
                ):
                    continue
                raise ProviderRequestError(reason)
            if not isinstance(raw, dict):
                self.last_request_meta["reason"] = "invalid_response"
                raise ProviderRequestError("invalid_response")
            self.last_request_meta["outcome"] = "completed"
            self.last_request_meta.pop("reason", None)
            return raw
        raise AssertionError("bounded attempt loop must return or raise")

    def close(self) -> None:
        """Close only the Redis client created here; HTTP ownership stays with adapter."""
        if self._owned_redis is not None:
            self._owned_redis.close()
            self._owned_redis = None
