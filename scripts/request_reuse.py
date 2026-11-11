"""Bounded response reuse and fenced request coalescing on the existing Redis.

Running ownership deliberately has no TTL or takeover: an unknown paid send must
be reconciled by an operator. Successful results and error notifications expire.
This is an expendable transport cache, never a second football facts database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote, quote_plus
from uuid import uuid4

import httpx
from redis import Redis
from redis.exceptions import RedisError

from scripts.request_quota import QuotaDenied, RedisQuotaLedger

_CREDENTIAL_FIELDS = {
    "apikey",
    "api-key",
    "api_key",
    "key",
    "token",
    "x-api-key",
    "x-apisports-key",
}


class ReuseUnavailable(RuntimeError):
    """Only bounded local reasons; never exposes request/Redis/provider secrets."""


@dataclass(frozen=True)
class ReusePolicy:
    permission_scope: str
    ttl_seconds: int = 60
    wait_ms: int = 10_000
    max_payload_bytes: int = 262_144

    def __post_init__(self) -> None:
        if not isinstance(self.permission_scope, str) or not re.fullmatch(
            r"[a-zA-Z0-9_.:-]{1,128}", self.permission_scope
        ):
            raise ValueError("explicit non-secret permission revision is required")
        for value, lower, upper in (
            (self.ttl_seconds, 1, 300),
            (self.wait_ms, 0, 30_000),
            (self.max_payload_bytes, 1, 1_048_576),
        ):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("reuse policy must use bounded integer values")


_SCRIPT = """
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1])*1000 + math.floor(tonumber(now_parts[2])/1000)
local action, token, arg = ARGV[1], ARGV[2], cjson.decode(ARGV[3])
local raw = redis.call('GET', KEYS[1])
local function result(kind, extra)
    local r = extra or {}
    r.kind, r.now_ms = kind, now
    return cjson.encode(r)
end
if not raw then
    if action ~= 'claim' then return result('request_owner_lost') end
    redis.call('SET', KEYS[1], cjson.encode({schema='request-reuse/v1',
        state='running', token=token, started_at_ms=now}))
    return result('owner')
end
if string.len(raw) > arg.max_payload_bytes*6 + 2048 then
    return result('reuse_state_invalid')
end
local valid, s = pcall(cjson.decode, raw)
if not valid or type(s) ~= 'table' or s.schema ~= 'request-reuse/v1' then
    return result('reuse_state_invalid')
end
local ttl = redis.call('PTTL', KEYS[1])
if s.state == 'running' then
    if ttl ~= -1 or type(s.token) ~= 'string' or s.token == ''
        or type(s.started_at_ms) ~= 'number' or s.started_at_ms <= 0 then
        return result('reuse_state_invalid')
    end
    if action == 'finish' then
        if s.token ~= token then return result('request_owner_lost') end
        local entry = {schema='request-reuse/v1', state=arg.state, fetched_at_ms=now,
            body=arg.body, reason=arg.reason}
        redis.call('SET', KEYS[1], cjson.encode(entry), 'PX', arg.ttl_ms)
        return result('published', {fetched_at_ms=now})
    end
    if now < s.started_at_ms or now-s.started_at_ms >= 120000 then
        return result('request_inflight_uncertain')
    end
    return result('waiting')
end
if action == 'finish' then return result('request_owner_lost') end
if ttl <= 0 or type(s.fetched_at_ms) ~= 'number' or s.fetched_at_ms > now
    or s.fetched_at_ms <= 0 or s.fetched_at_ms ~= math.floor(s.fetched_at_ms) then
    return result('reuse_state_invalid')
end
if s.state == 'success' and type(s.body) == 'string'
    and ttl <= arg.ttl_ms and now-s.fetched_at_ms <= arg.ttl_ms then
    return result('cached', {body=s.body, fetched_at_ms=s.fetched_at_ms})
end
if s.state == 'failed' and ttl <= 30000 and now-s.fetched_at_ms <= 30000
    and (s.reason == 'shared_request_failed' or s.reason == 'shared_result_not_reusable') then
    return result(s.reason)
end
return result('reuse_state_invalid')
"""


class RedisRequestReuse:
    def __init__(
        self,
        client: Redis,
        ledger: RedisQuotaLedger,
        policy: ReusePolicy,
        *,
        credential: str,
    ) -> None:
        if not isinstance(credential, str) or not credential.strip():
            raise ValueError("reuse credential required")
        self._client = client
        self._ledger = ledger
        self.policy = policy
        self._credential = credential
        self._credential_id = hashlib.sha256(credential.encode()).hexdigest()
        self._identity = self._ledger_identity(ledger)
        self._http: httpx.Client | None = None

    def bind_transport(self, client: Any) -> None:
        """Identity must include HTTPX defaults, cookies and default parameters."""
        if not isinstance(client, httpx.Client) or (
            self._http is not None and self._http is not client
        ):
            raise ReuseUnavailable("request_identity_invalid")
        self._http = client

    @staticmethod
    def _ledger_identity(ledger: RedisQuotaLedger) -> str:
        return json.dumps([asdict(ledger.policy), ledger.environment], sort_keys=True)

    def matches(self, ledger: RedisQuotaLedger, credential: str) -> bool:
        return (
            self._ledger is ledger
            and self._identity == self._ledger_identity(ledger)
            and hmac.compare_digest(
                self._credential_id, hashlib.sha256(credential.encode()).hexdigest()
            )
        )

    def key(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        priority: bool = False,
    ) -> str:
        try:
            if self._http is not None:
                if self._http.auth is not None or any(self._http.event_hooks.values()):
                    raise ValueError  # Auth flows may mutate requests after build_request.
                request = self._http.build_request("GET", url, headers=headers, params=params)
            else:
                request = httpx.Request("GET", url, headers=headers, params=params)
            query = sorted(request.url.params.multi_items(), key=lambda pair: pair[0])
            normalized_headers = sorted(request.headers.multi_items(), key=lambda pair: pair[0])
            for name, value in query + normalized_headers:
                if name.lower() in _CREDENTIAL_FIELDS and not hmac.compare_digest(
                    value.encode(), self._credential.encode()
                ):
                    raise ValueError
            raw = json.dumps(
                [
                    "request-reuse/v1",
                    self._identity,
                    asdict(self.policy),
                    self._credential_id,
                    "GET",
                    str(request.url.copy_with(query=None)),
                    query,
                    normalized_headers,
                    priority,
                ],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except ValueError, TypeError, httpx.InvalidURL:
            raise ReuseUnavailable("request_identity_invalid") from None
        return "fqp:request-reuse:v1:{" + hashlib.sha256(raw.encode()).hexdigest() + "}"

    def _execute(self, key: str, action: str, token: str, **kwargs: Any) -> dict[str, Any]:
        try:
            raw = self._client.eval(
                _SCRIPT,
                1,
                key,
                action,
                token,
                json.dumps(
                    {
                        "max_payload_bytes": self.policy.max_payload_bytes,
                        "ttl_ms": self.policy.ttl_seconds * 1000,
                        **kwargs,
                    },
                    allow_nan=False,
                ),
            )
            result = json.loads(raw)
            if not isinstance(result, dict) or not isinstance(result.get("kind"), str):
                raise ValueError
            return result
        except RedisError, TypeError, ValueError:
            raise ReuseUnavailable("reuse_store_unavailable") from None

    def _permission(self) -> None:
        state = self._ledger.snapshot()
        if state["blocked"]:
            raise QuotaDenied(state["blocked"])

    def _cacheable(self, payload: dict[str, Any]) -> str | None:
        provider = self._ledger.policy.provider
        if provider == "api_football":
            valid = not payload.get("errors") and isinstance(payload.get("response"), (list, dict))
        elif provider == "newsapi":
            valid = payload.get("status") == "ok" and isinstance(payload.get("articles"), list)
        elif provider == "gnews":
            valid = not payload.get("errors") and isinstance(payload.get("articles"), list)
        elif provider == "guardian":
            body = payload.get("response")
            valid = (
                isinstance(body, dict)
                and body.get("status") == "ok"
                and isinstance(body.get("results"), list)
            )
        else:
            valid = False
        if not valid:
            return None
        try:
            body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except ValueError, TypeError:
            return None
        secrets = (
            self._credential,
            json.dumps(self._credential, ensure_ascii=False)[1:-1],
            quote(self._credential, safe=""),
            quote_plus(self._credential),
        )
        if len(body.encode()) > self.policy.max_payload_bytes or any(
            value in body for value in secrets
        ):
            return None
        return body

    def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None,
        params: dict[str, Any] | None,
        priority: bool,
        load: Callable[[], dict[str, Any]],
        meta: dict[str, Any],
    ) -> dict[str, Any]:
        key = self.key(url, headers=headers, params=params, priority=priority)
        token = uuid4().hex
        deadline = time.monotonic() + self.policy.wait_ms / 1000
        waited = False
        while True:
            self._permission()
            entry = self._execute(key, "claim", token)
            kind = entry["kind"]
            if kind == "owner":
                break
            if kind == "cached":
                try:
                    payload = json.loads(entry["body"])
                    if not isinstance(payload, dict) or self._cacheable(payload) is None:
                        raise ValueError
                except ValueError, TypeError, KeyError:
                    raise ReuseUnavailable("reuse_state_invalid") from None
                self._permission()
                meta.update(
                    reuse_status="coalesced" if waited else "cache_hit",
                    outcome="completed",
                    fetched_at_ms=entry["fetched_at_ms"],
                    age_ms=entry["now_ms"] - entry["fetched_at_ms"],
                )
                return payload
            if kind != "waiting":
                raise ReuseUnavailable(kind)
            waited = True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReuseUnavailable("request_wait_timeout")
            time.sleep(min(0.05, remaining))
        meta["reuse_status"] = "fetched"
        try:
            payload = load()
        except Exception:
            self._finish(key, token, body=None, reason="shared_request_failed")
            raise
        body = (
            self._cacheable(payload)
            if self.key(url, headers=headers, params=params, priority=priority) == key
            else None
        )
        result = self._finish(
            key, token, body=body, reason="shared_result_not_reusable" if body is None else None
        )
        self._permission()
        meta.update(
            reuse_status="fetched" if body is not None else "not_stored",
            fetched_at_ms=result["fetched_at_ms"],
            age_ms=0,
        )
        return payload

    def _finish(
        self, key: str, token: str, *, body: str | None, reason: str | None
    ) -> dict[str, Any]:
        result = self._execute(
            key,
            "finish",
            token,
            state="success" if body is not None else "failed",
            body=body,
            reason=reason,
            ttl_ms=self.policy.ttl_seconds * 1000 if body is not None else 30000,
        )
        if result["kind"] != "published":
            raise ReuseUnavailable(result["kind"])
        return result
