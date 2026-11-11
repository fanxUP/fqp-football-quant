"""Atomic account quota permits in the existing Redis service.

This primitive does not send HTTP or initialize/reset missing ledgers. Current
collectors are not migrated yet; activation requirements are in request-governance.md.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any
from uuid import uuid4

from redis.exceptions import RedisError

_NAME = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")


def _integer(value: object, *, maximum: int = 10_000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError("quota values must be bounded nonnegative integers")
    return value


class QuotaUnavailable(RuntimeError):
    """No permit can be obtained; callers must not bypass the ledger."""


class QuotaDenied(RuntimeError):
    """A shared rule denied the operation; no secrets are included."""

    def __init__(self, reason: str, retry_after_ms: int = 0) -> None:
        self.reason = reason
        self.retry_after_ms = retry_after_ms
        super().__init__(reason)


@dataclass(frozen=True)
class QuotaPolicy:
    provider: str
    account_scope: str
    daily_limit: int
    minute_limit: int
    environment_limits: tuple[tuple[str, int], ...]
    priority_reserve: int = 0
    day_reset_offset_seconds: int = 0
    minimum_interval_ms: int = 0
    lease_ms: int = 30_000

    def __post_init__(self) -> None:
        for name in (self.provider, self.account_scope):
            if not isinstance(name, str) or not _NAME.fullmatch(name):
                raise ValueError("provider and account_scope must be non-secret identifiers")
        _integer(self.daily_limit)
        _integer(self.minute_limit)
        _integer(self.priority_reserve, maximum=self.daily_limit)
        _integer(self.day_reset_offset_seconds, maximum=86_399)
        _integer(self.minimum_interval_ms, maximum=60_000)
        if not _integer(self.lease_ms, maximum=60_000):
            raise ValueError("permit lease must be positive")
        if not self.environment_limits or len(self.environment_limits) > 16:
            raise ValueError("explicit bounded environment allocations are required")
        names: set[str] = set()
        total = 0
        for name, limit in self.environment_limits:
            if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
                raise ValueError("environment allocations require unique identifiers")
            names.add(name)
            total += _integer(limit, maximum=self.daily_limit)
        if total > self.daily_limit:
            raise ValueError("environment allocations exceed account daily budget")
        object.__setattr__(
            self,
            "environment_limits",
            tuple(sorted((name, limit) for name, limit in self.environment_limits)),
        )


@dataclass(frozen=True)
class SendReceipt:
    ledger_key: str
    day: int
    minute: int
    day_sent: int
    minute_sent: int


# One persistent account key: no per-process/day/environment keys that could
# silently reopen quota after a worker restart, eviction or configuration change.
# Mutations are committed once at the end of the Lua operation.
_SCRIPT = """
local action, policy_id = ARGV[1], ARGV[2]
local p, arg = cjson.decode(ARGV[3]), cjson.decode(ARGV[4])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local day = math.floor((now / 1000 - p.day_reset_offset_seconds) / 86400)
local minute = math.floor(now / 60000)
local raw = redis.call('GET', KEYS[1])
local function error_result(reason, wait)
    return cjson.encode({ok=false, reason=reason, retry_after_ms=wait or 0})
end
if action == 'provision' then
    if raw then return error_result('ledger_exists') end
    local used = 0
    for _, count in pairs(arg.daily_usage) do used = used + count end
    local s = {schema='quota/v1', policy_id=policy_id, last_time_ms=now,
        day=day, minute=minute, day_used=used, day_sent=used,
        minute_used=arg.minute_usage, minute_sent=arg.minute_usage,
        environment_used=arg.daily_usage, day_ceiling=p.daily_limit,
        minute_ceiling=p.minute_limit, reserve_released=false,
        last_sent_ms=0, blocked='', not_before_ms=0, permits={}}
    redis.call('SET', KEYS[1], cjson.encode(s))
    return cjson.encode({ok=true})
end
if not raw then return error_result('ledger_missing') end
if redis.call('PTTL', KEYS[1]) ~= -1 then return error_result('ledger_expiring') end
local decoded, s = pcall(cjson.decode, raw)
if not decoded or type(s) ~= 'table' or s.schema ~= 'quota/v1' then
    return error_result('ledger_corrupt')
end
if s.policy_id ~= policy_id then return error_result('policy_mismatch') end
-- Missing/corrupt required state must fail instead of recreating counters.
if type(s.day) ~= 'number' or type(s.minute) ~= 'number'
    or type(s.last_time_ms) ~= 'number' or type(s.day_used) ~= 'number'
    or type(s.day_sent) ~= 'number' or type(s.minute_used) ~= 'number'
    or type(s.minute_sent) ~= 'number' or type(s.day_ceiling) ~= 'number'
    or type(s.minute_ceiling) ~= 'number' or type(s.environment_used) ~= 'table'
    or type(s.permits) ~= 'table' or type(s.not_before_ms) ~= 'number'
    or type(s.last_sent_ms) ~= 'number' or type(s.blocked) ~= 'string'
    or type(s.reserve_released) ~= 'boolean' then
    return error_result('ledger_corrupt')
end
for _, allocation in ipairs(p.environment_limits) do
    if type(s.environment_used[allocation[1]]) ~= 'number' then
        return error_result('ledger_corrupt')
    end
end
local function count(value, maximum)
    return type(value) == 'number' and value >= 0
        and value == math.floor(value) and value <= maximum
end
if not count(s.day_used, p.daily_limit) or not count(s.day_sent, s.day_used)
    or not count(s.minute_used, p.minute_limit) or not count(s.minute_sent, s.minute_used)
    or not count(s.day_ceiling, p.daily_limit) or not count(s.minute_ceiling, p.minute_limit)
    or not count(s.day, 1000000) or not count(s.minute, 2000000000)
    or not count(s.last_time_ms, 1000000000000000)
    or not count(s.not_before_ms, 1000000000000000)
    or not count(s.last_sent_ms, s.last_time_ms)
    or (s.blocked ~= '' and s.blocked ~= 'authentication_denied' and s.blocked ~= 'plan_denied') then
    return error_result('ledger_corrupt')
end
local environment_sum = 0
for _, allocation in ipairs(p.environment_limits) do
    local used = s.environment_used[allocation[1]]
    if not count(used, allocation[2]) then return error_result('ledger_corrupt') end
    environment_sum = environment_sum + used
end
if environment_sum ~= s.day_used then return error_result('ledger_corrupt') end
for _, permit in pairs(s.permits) do
    if type(permit) ~= 'table' or type(permit.environment) ~= 'string'
        or s.environment_used[permit.environment] == nil
        or not count(permit.expires, 1000000000000000)
        or not count(permit.day, 1000000) or not count(permit.minute, 2000000000) then
        return error_result('ledger_corrupt')
    end
end
if now < s.last_time_ms then return error_result('clock_regression') end
s.last_time_ms = now
if day ~= s.day then
    if day < s.day then return error_result('clock_regression') end
    s.day, s.day_used, s.day_sent, s.day_ceiling = day, 0, 0, p.daily_limit
    s.reserve_released = false
    for name, _ in pairs(s.environment_used) do s.environment_used[name] = 0 end
end
if minute ~= s.minute then
    if minute < s.minute then return error_result('clock_regression') end
    s.minute, s.minute_used, s.minute_sent, s.minute_ceiling = minute, 0, 0, p.minute_limit
end
for token, permit in pairs(s.permits) do
    if permit.expires <= now or permit.day ~= day or permit.minute ~= minute then
        -- Expiry is not proof of non-billing. Never automatically refund.
        s.permits[token] = nil
    end
end
local function save(result)
    redis.call('SET', KEYS[1], cjson.encode(s))
    return cjson.encode(result)
end
local function deny(reason, wait)
    return save({ok=false, reason=reason, retry_after_ms=wait or 0})
end
local function send_block()
    if s.blocked ~= '' then return s.blocked, 0 end
    if s.not_before_ms > now then return 'cooldown', s.not_before_ms - now end
    return nil, 0
end
local day_end = ((day + 1) * 86400 + p.day_reset_offset_seconds) * 1000
local minute_end = (minute + 1) * 60000
if action == 'reserve' then
    local reason, wait = send_block()
    if reason then return deny(reason, wait) end
    if s.day_used >= p.daily_limit then return deny('daily_budget', day_end - now) end
    if s.day_used >= s.day_ceiling then return deny('provider_daily_budget', day_end - now) end
    local allocation = 0
    for _, item in ipairs(p.environment_limits) do
        if item[1] == arg.environment then allocation = item[2] end
    end
    if s.environment_used[arg.environment] >= allocation then
        return deny('environment_budget', day_end - now)
    end
    if not arg.priority and not s.reserve_released
        and s.day_used >= p.daily_limit - p.priority_reserve then
        return deny('priority_reserved', day_end - now)
    end
    if s.minute_used >= p.minute_limit then return deny('minute_budget', minute_end - now) end
    if s.minute_used >= s.minute_ceiling then
        return deny('provider_minute_budget', minute_end - now)
    end
    s.day_used, s.minute_used = s.day_used + 1, s.minute_used + 1
    s.environment_used[arg.environment] = s.environment_used[arg.environment] + 1
    s.permits[arg.token] = {environment=arg.environment, day=day, minute=minute,
        expires=math.min(now + p.lease_ms, day_end, minute_end)}
    return save({ok=true, token=arg.token})
elseif action == 'mark_sent' or action == 'cancel' then
    local permit = s.permits[arg.token]
    if not permit or permit.environment ~= arg.environment then
        if action == 'cancel' then return save({ok=true, cancelled=false}) end
        return deny('invalid_permit')
    end
    if action == 'cancel' then
        s.day_used, s.minute_used = s.day_used - 1, s.minute_used - 1
        s.environment_used[arg.environment] = s.environment_used[arg.environment] - 1
        s.permits[arg.token] = nil
        return save({ok=true, cancelled=true})
    end
    local reason, wait = send_block()
    if reason then return deny(reason, wait) end
    if s.day_sent >= s.day_ceiling then return deny('provider_daily_budget', day_end - now) end
    if s.minute_sent >= s.minute_ceiling then
        return deny('provider_minute_budget', minute_end - now)
    end
    if s.last_sent_ms + p.minimum_interval_ms > now then
        return deny('minimum_interval', s.last_sent_ms + p.minimum_interval_ms - now)
    end
    s.day_sent, s.minute_sent = s.day_sent + 1, s.minute_sent + 1
    s.last_sent_ms, s.permits[arg.token] = now, nil
    return save({ok=true, day=day, minute=minute,
        day_sent=s.day_sent, minute_sent=s.minute_sent})
elseif action == 'feedback' then
    local r = arg.receipt
    if r.day == day and (r.day_sent < 1 or r.day_sent > s.day_sent) then
        return deny('invalid_receipt')
    end
    if r.minute == minute and (r.minute_sent < 1 or r.minute_sent > s.minute_sent) then
        return deny('invalid_receipt')
    end
    if r.day == day and arg.daily_remaining ~= cjson.null then
        s.day_ceiling = math.min(s.day_ceiling, r.day_sent + arg.daily_remaining)
    end
    if r.minute == minute and arg.minute_remaining ~= cjson.null then
        s.minute_ceiling = math.min(s.minute_ceiling, r.minute_sent + arg.minute_remaining)
    end
    if arg.denied ~= cjson.null then s.blocked = arg.denied end
    s.not_before_ms = math.max(s.not_before_ms, now + arg.retry_after_ms)
    return save({ok=true})
elseif action == 'release_reserve' then
    s.reserve_released = true
    return save({ok=true})
elseif action == 'snapshot' then
    local public = {}
    for name, value in pairs(s) do
        if name ~= 'permits' and name ~= 'policy_id' then public[name] = value end
    end
    return save({ok=true, state=public})
end
return deny('unknown_action')
"""


class RedisQuotaLedger:
    """Internal primitive, not an authorization boundary or automatic provisioning tool.

    All environments sharing a provider account must use the same account_scope,
    policy and coordination Redis. The caller supplies a Redis client with bounded
    timeouts. Persistent no-eviction Redis and reconciled opening usage are required
    before live integration; this class does not change service configuration.
    """

    def __init__(self, client: Any, policy: QuotaPolicy, *, environment: str) -> None:
        if environment not in dict(policy.environment_limits):
            raise ValueError("environment is not allocated quota")
        self._client = client
        self.policy = policy
        self.environment = environment
        digest = hashlib.sha256(f"{policy.provider}\0{policy.account_scope}".encode()).hexdigest()
        self.key = f"fqp:request-quota:v1:{{{digest}}}"
        self._policy_json = json.dumps(asdict(policy), sort_keys=True, separators=(",", ":"))
        self._policy_id = hashlib.sha256(self._policy_json.encode()).hexdigest()

    def _execute(self, action: str, **arguments: Any) -> dict[str, Any]:
        try:
            raw = self._client.eval(
                _SCRIPT,
                1,
                self.key,
                action,
                self._policy_id,
                self._policy_json,
                json.dumps({"environment": self.environment, **arguments}, allow_nan=False),
            )
            result = json.loads(raw)
            if not isinstance(result, dict) or type(result.get("ok")) is not bool:
                raise ValueError("invalid quota response")
        except RedisError, TypeError, ValueError:
            # URL, credentials and raw provider/Redis errors never enter outward errors.
            raise QuotaUnavailable("quota_store_unavailable") from None
        if not result["ok"]:
            raise QuotaDenied(str(result["reason"]), int(result.get("retry_after_ms", 0)))
        return result

    def provision(self, *, daily_usage: dict[str, int], minute_usage: int) -> None:
        """Explicit opening usage only; never call this from an HTTP retry path."""
        allocations = dict(self.policy.environment_limits)
        if daily_usage.keys() != allocations.keys():
            raise ValueError("opening usage must include every allocated environment")
        for name, count in daily_usage.items():
            _integer(count, maximum=allocations[name])
        _integer(minute_usage, maximum=self.policy.minute_limit)
        if minute_usage > sum(daily_usage.values()):
            raise ValueError("minute usage cannot exceed daily usage")
        self._execute("provision", daily_usage=daily_usage, minute_usage=minute_usage)

    def reserve(self, *, priority: bool = False) -> str:
        if type(priority) is not bool:
            raise ValueError("priority must be boolean")
        return str(self._execute("reserve", token=uuid4().hex, priority=priority)["token"])

    def mark_sent(self, token: str) -> SendReceipt:
        """Consume once immediately before transport; timeout/crash stays charged."""
        result = self._execute("mark_sent", token=token)
        return SendReceipt(
            self.key, result["day"], result["minute"], result["day_sent"], result["minute_sent"]
        )

    def cancel(self, token: str) -> bool:
        """Release only a still-valid, unconsumed reservation in this environment."""
        return bool(self._execute("cancel", token=token)["cancelled"])

    def snapshot(self) -> dict[str, Any]:
        """Refresh clock windows and return counters; this is not a read-only command."""
        return dict(self._execute("snapshot")["state"])

    def release_priority_reserve(self) -> None:
        """Release today's reserved slice, without adding quota to the account."""
        self._execute("release_reserve")

    def apply_feedback(
        self,
        receipt: SendReceipt,
        *,
        daily_remaining: int | None = None,
        minute_remaining: int | None = None,
        retry_after_ms: int = 0,
        denied: str | None = None,
    ) -> None:
        """Tighten only; HTTP-specific header/window validation belongs to adapters.

        Sent sequence numbers discount later outstanding permits. Delayed replies
        cannot increase a ceiling or apply an old window's remaining count to a
        new window. Authentication/plan blocks intentionally require operator review.
        """
        if receipt.ledger_key != self.key:
            raise ValueError("receipt belongs to a different account ledger")
        _integer(receipt.day, maximum=1_000_000)
        _integer(receipt.minute, maximum=2_000_000_000)
        for sequence in (receipt.day_sent, receipt.minute_sent):
            if not _integer(sequence, maximum=1_000_000):
                raise ValueError("receipt must describe an actual send")
        for count in (daily_remaining, minute_remaining):
            if count is not None:
                _integer(count, maximum=1_000_000)
        _integer(retry_after_ms, maximum=604_800_000)
        if denied not in (None, "authentication_denied", "plan_denied"):
            raise ValueError("unknown persistent denial")
        self._execute(
            "feedback",
            receipt=asdict(receipt),
            daily_remaining=daily_remaining,
            minute_remaining=minute_remaining,
            retry_after_ms=retry_after_ms,
            denied=denied,
        )
