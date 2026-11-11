"""Bounded single-flight history cache with explicit data/cache freshness."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from apps.backend.src.db import get_db
from scripts.model_performance import get_model_performance_history_auto

_logger = logging.getLogger(__name__)
_FRESH_SECONDS = 120
_MAX_STALE_SECONDS = 3600
_REFRESH_LOCK_SECONDS = 30
_CACHE_PREFIX = "fqp:model-performance-history:v2"
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""
_redis_client: Redis | None = None
_redis_client_lock = threading.Lock()
_compute_lock = threading.Lock()
_local_lock = threading.Lock()
_background_lock = threading.Lock()
_last_good: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()


class ModelHistoryUnavailable(RuntimeError):
    """A computation is already running or the bounded database query failed."""


def _get_redis_client() -> Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    with _redis_client_lock:
        if _redis_client is None:
            try:
                _redis_client = Redis.from_url(
                    os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
                    decode_responses=True,
                    socket_connect_timeout=0.25,
                    socket_timeout=0.25,
                )
            except RedisError, ValueError:
                _logger.debug("Model history Redis configuration is unavailable", exc_info=True)
    return _redis_client


def _cache_key(window: int, days: int) -> str:
    return f"{_CACHE_PREFIX}:{window}:{days}"


def _read_cached_payload(client: Redis, key: str) -> tuple[dict[str, Any], float] | None:
    try:
        raw = client.get(key)
        if not raw:
            return None
        envelope = json.loads(raw)
        payload, cached_at = envelope["payload"], float(envelope["cached_at"])
        if not isinstance(payload, dict):
            return None
        return payload, max(0.0, time.time() - cached_at)
    except RedisError, KeyError, TypeError, ValueError:
        _logger.debug("Model history cache read failed", exc_info=True)
        return None


def _read_local(key: str) -> tuple[dict[str, Any], float] | None:
    with _local_lock:
        cached = _last_good.get(key)
        if cached:
            payload, cached_at = cached
            age = max(0.0, time.time() - cached_at)
            if age <= _MAX_STALE_SECONDS:
                return payload, age
            del _last_good[key]
    return None


def _write_cached_payload(client: Redis | None, key: str, payload: dict[str, Any]) -> None:
    cached_at = time.time()
    with _local_lock:
        _last_good[key] = payload, cached_at
        _last_good.move_to_end(key)
        while len(_last_good) > 32:
            _last_good.popitem(last=False)
    if client is None:
        return
    try:
        client.setex(
            key,
            _MAX_STALE_SECONDS,
            json.dumps(
                {"cached_at": cached_at, "payload": payload},
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ),
        )
    except RedisError, TypeError, ValueError:
        _logger.debug("Model history cache write failed", exc_info=True)


def _decorate(payload: dict[str, Any], age: float) -> dict[str, Any]:
    return {
        **payload,
        "cacheAgeSeconds": round(age),
        "stale": bool(payload.get("stale")) or age > _FRESH_SECONDS,
    }


def _compute_history(window: int, days: int) -> dict[str, Any]:
    if not _compute_lock.acquire(timeout=2):
        raise ModelHistoryUnavailable("History refresh already running")
    try:
        local = _read_local(_cache_key(window, days))
        if local and local[1] <= _FRESH_SECONDS:
            return local[0]
        with get_db() as conn:
            # PostgreSQL coordinates workers even when Redis is unavailable.
            lock_id = int.from_bytes(
                hashlib.sha256(_cache_key(window, days).encode()).digest()[:8], "big"
            ) & ((1 << 63) - 1)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (lock_id,))
                if not cur.fetchone()[0]:
                    raise ModelHistoryUnavailable("History refresh already running")
            payload = get_model_performance_history_auto(conn, window=window, days=days)
            payload["generatedAt"] = datetime.now(UTC).isoformat()
            # Release the transaction lock before returning the pooled connection.
            conn.rollback()
            _write_cached_payload(None, _cache_key(window, days), payload)
            return payload
    except ModelHistoryUnavailable:
        raise
    except Exception as exc:
        _logger.warning("Bounded model history query failed: %s", type(exc).__name__)
        raise ModelHistoryUnavailable("History refresh temporarily unavailable") from exc
    finally:
        _compute_lock.release()


def _release_refresh_lock(client: Redis, lock_key: str, token: str) -> None:
    try:
        client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
    except RedisError:
        _logger.debug("History refresh lock expires automatically", exc_info=True)


def _refresh_in_background(
    client: Redis | None, key: str, lock_key: str, token: str, window: int, days: int
) -> None:
    try:
        _write_cached_payload(client, key, _compute_history(window, days))
    except ModelHistoryUnavailable:
        _logger.info("History background refresh deferred")
    finally:
        if client is not None:
            _release_refresh_lock(client, lock_key, token)
        _background_lock.release()


def _schedule_refresh(client: Redis, key: str, window: int, days: int) -> None:
    if not _background_lock.acquire(blocking=False):
        return
    refresh_client: Redis | None = client
    lock_key, token = f"{key}:refresh-lock", uuid.uuid4().hex
    try:
        if not client.set(lock_key, token, nx=True, ex=_REFRESH_LOCK_SECONDS):
            _background_lock.release()
            return
    except RedisError:
        # Redis outage: a single local background worker plus PostgreSQL lock.
        refresh_client = None
    worker = threading.Thread(
        target=_refresh_in_background,
        args=(refresh_client, key, lock_key, token, window, days),
        name="model-history-cache-refresh",
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        if refresh_client is not None:
            _release_refresh_lock(refresh_client, lock_key, token)
        _background_lock.release()


def get_cached_model_performance_history(*, window: int = 20, days: int = 365) -> dict[str, Any]:
    client, key = _get_redis_client(), _cache_key(window, days)
    cached = _read_cached_payload(client, key) if client else None
    cached = cached or _read_local(key)
    if cached and cached[1] <= _MAX_STALE_SECONDS:
        payload, age = cached
        if age <= _FRESH_SECONDS:
            return _decorate(payload, age)
        if client is not None:
            _schedule_refresh(client, key, window, days)
            return _decorate(payload, age)
        # With no Redis client, the database lock still bounds refresh work.

    lock_key, token, acquired = f"{key}:refresh-lock", uuid.uuid4().hex, False
    if client is not None:
        try:
            acquired = bool(client.set(lock_key, token, nx=True, ex=_REFRESH_LOCK_SECONDS))
            if not acquired:
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    refreshed = _read_cached_payload(client, key)
                    if refreshed:
                        return _decorate(*refreshed)
                    time.sleep(0.1)
                raise ModelHistoryUnavailable("History refresh already running")
        except RedisError:
            client = None
    try:
        payload = _compute_history(window, days)
        _write_cached_payload(client, key, payload)
        return _decorate(payload, 0)
    except ModelHistoryUnavailable:
        if cached:
            return _decorate(*cached)
        raise
    finally:
        if client is not None and acquired:
            _release_refresh_lock(client, lock_key, token)
