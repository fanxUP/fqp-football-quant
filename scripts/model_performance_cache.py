"""Shared Redis cache for model performance history responses."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from apps.backend.src.db import get_db
from scripts.model_performance import get_model_performance_history_auto

_logger = logging.getLogger(__name__)
_FRESH_SECONDS = 120
_MAX_STALE_SECONDS = 600
_CACHE_TTL_SECONDS = _MAX_STALE_SECONDS
_REFRESH_LOCK_SECONDS = 300
_CACHE_PREFIX = "fqp:model-performance-history:v1"
_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

_redis_client: Redis | None = None
_redis_client_lock = threading.Lock()


def _get_redis_client() -> Redis | None:
    global _redis_client
    if _redis_client is not None:
        return _redis_client

    with _redis_client_lock:
        if _redis_client is not None:
            return _redis_client
        try:
            _redis_client = Redis.from_url(
                os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0"),
                decode_responses=True,
                socket_connect_timeout=0.25,
                socket_timeout=0.25,
            )
        except RedisError, ValueError:
            _logger.debug("Model history Redis cache is unavailable", exc_info=True)
            return None
    return _redis_client


def _cache_key(window: int, days: int) -> str:
    return f"{_CACHE_PREFIX}:{window}:{days}"


def _read_cached_payload(client: Redis, key: str) -> tuple[dict[str, Any], float] | None:
    try:
        raw = client.get(key)
    except RedisError:
        _logger.debug("Model history Redis read failed", exc_info=True)
        return None
    if not raw:
        return None

    try:
        envelope = json.loads(raw)
        payload = envelope["payload"]
        cached_at = float(envelope["cached_at"])
        if not isinstance(payload, dict):
            raise ValueError("cached model history payload is not an object")
        return payload, max(0.0, time.time() - cached_at)
    except KeyError, TypeError, ValueError, json.JSONDecodeError:
        try:
            client.delete(key)
        except RedisError:
            _logger.debug("Could not remove invalid model history cache", exc_info=True)
        return None


def _write_cached_payload(client: Redis, key: str, payload: dict[str, Any]) -> None:
    try:
        envelope = json.dumps(
            {"cached_at": time.time(), "payload": payload},
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
        client.setex(key, _CACHE_TTL_SECONDS, envelope)
    except RedisError, TypeError, ValueError:
        _logger.debug("Model history Redis write failed", exc_info=True)


def _compute_history(window: int, days: int) -> dict[str, Any]:
    with get_db() as conn:
        return get_model_performance_history_auto(conn, window=window, days=days)


def _release_refresh_lock(client: Redis, lock_key: str, token: str) -> None:
    try:
        client.eval(_RELEASE_LOCK_SCRIPT, 1, lock_key, token)
    except RedisError:
        # The lock has a short TTL, so a cache outage cannot leave it permanent.
        _logger.debug("Could not release model history refresh lock", exc_info=True)


def _refresh_in_background(
    client: Redis,
    key: str,
    lock_key: str,
    token: str,
    window: int,
    days: int,
) -> None:
    try:
        _write_cached_payload(client, key, _compute_history(window, days))
    except Exception:
        _logger.exception("Model history background refresh failed")
    finally:
        _release_refresh_lock(client, lock_key, token)


def _schedule_refresh(client: Redis, key: str, window: int, days: int) -> None:
    lock_key = f"{key}:refresh-lock"
    token = uuid.uuid4().hex
    try:
        acquired = client.set(lock_key, token, nx=True, ex=_REFRESH_LOCK_SECONDS)
    except RedisError:
        _logger.debug("Could not acquire model history refresh lock", exc_info=True)
        return
    if not acquired:
        return

    worker = threading.Thread(
        target=_refresh_in_background,
        args=(client, key, lock_key, token, window, days),
        name="model-history-cache-refresh",
        daemon=True,
    )
    try:
        worker.start()
    except RuntimeError:
        _release_refresh_lock(client, lock_key, token)
        _logger.exception("Could not start model history background refresh")


def get_cached_model_performance_history(*, window: int = 20, days: int = 365) -> dict[str, Any]:
    """Return fresh cached history, refresh stale history in the background, or query PostgreSQL."""
    client = _get_redis_client()
    key = _cache_key(window, days)

    if client is not None:
        cached = _read_cached_payload(client, key)
        if cached is not None:
            payload, age_seconds = cached
            if age_seconds <= _FRESH_SECONDS:
                return payload
            if age_seconds <= _MAX_STALE_SECONDS:
                _schedule_refresh(client, key, window, days)
                return payload

    payload = _compute_history(window, days)
    if client is not None:
        _write_cached_payload(client, key, payload)
    return payload
