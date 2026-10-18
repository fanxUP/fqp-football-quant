"""Bounded read-only Redis observations; never grants live source activation.

Run with FQP_REQUEST_RUNTIME_REDIS_URL and a dedicated observer credential.
Exit 0: sampled checks OK, 1: attention, 2: incomplete/unavailable. No writes,
ledger snapshots, owner takeover or automatic repairs are performed.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

_PREFIX = "fqp:request-reuse:v1:"
_KEY = re.compile(re.escape(_PREFIX) + r"\{[0-9a-f]{64}\}\Z")


def inspect_redis(client: Redis, *, max_pages: int = 20, max_keys: int = 200) -> dict[str, Any]:
    """Observe a bounded sample. SCAN/TTL/value reads are not one consistent view."""
    report: dict[str, Any] = {
        "status": "unavailable",
        "read_only": True,
        "activation_verified": False,
        "point_in_time_consistency": False,
        "issues": [],
    }
    deadline = time.monotonic() + 5

    def read(method, *args, **kwargs):
        if time.monotonic() >= deadline:
            raise TimeoutError
        return method(*args, **kwargs)

    issues = report["issues"]
    try:
        if type(max_pages) is not int or not 1 <= max_pages <= 20:
            raise ValueError
        if type(max_keys) is not int or not 1 <= max_keys <= 200:
            raise ValueError
        persistence = read(client.info, "persistence")
        replication = read(client.info, "replication")
        memory = read(client.info, "memory")
        stats = read(client.info, "stats")
        config = read(
            client.config_get,
            "appendonly",
            "appendfsync",
            "maxmemory",
            "maxmemory-policy",
            "stop-writes-on-bgsave-error",
        )
        default = read(client.acl_getuser, "default")
        limit = int(config.get("maxmemory", 0))
        used = int(memory["used_memory"])
        report["redis"] = {
            "aof_enabled": persistence.get("aof_enabled") == 1,
            "fsync_always": config.get("appendfsync") == "always",
            "primary": replication.get("role") == "master",
            "maxmemory_bytes": limit,
            "used_memory_bytes": used,
            "rss_bytes": int(memory["used_memory_rss"]),
            "noeviction": config.get("maxmemory-policy") == "noeviction",
            "evicted_keys": int(stats["evicted_keys"]),
            "default_user_disabled": bool(default) and "off" in default.get("flags", []),
        }
        if (
            config.get("appendonly") != "yes"
            or config.get("appendfsync") != "always"
            or config.get("stop-writes-on-bgsave-error") != "yes"
        ):
            issues.append("persistence_configuration")
        if (
            persistence.get("aof_enabled") != 1
            or persistence.get("loading") != 0
            or persistence.get("aof_last_write_status") != "ok"
            or persistence.get("aof_last_bgrewrite_status") != "ok"
        ):
            issues.append("persistence_health")
        if replication.get("role") != "master":
            issues.append("not_primary")
        if limit <= 0 or config.get("maxmemory-policy") != "noeviction":
            issues.append("memory_configuration")
        elif used >= limit * 0.8:
            issues.append("memory_pressure")
        if int(stats["evicted_keys"]) != 0:
            issues.append("historical_evictions")
        if not report["redis"]["default_user_disabled"]:
            issues.append("default_user_enabled")
        owners = {
            "pages": 0,
            "inspected": 0,
            "running": 0,
            "uncertain": 0,
            "invalid": 0,
            "expiring": 0,
            "disappeared": 0,
            "changed": 0,
            "max_age_ms": 0,
            "scan_complete": False,
        }
        report["owners"] = owners
        cursor = 0
        seen: set[str] = set()
        truncated = False
        for _ in range(max_pages):
            cursor, keys = read(client.scan, cursor=cursor, match=_PREFIX + "*", count=50)
            owners["pages"] += 1
            for key in keys:
                if key in seen:
                    continue
                if len(seen) >= max_keys:
                    truncated = True
                    break
                seen.add(key)
                owners["inspected"] += 1
                if not isinstance(key, str) or not _KEY.fullmatch(key):
                    owners["invalid"] += 1
                    continue
                ttl = read(client.pttl, key)
                if ttl == -2:
                    owners["disappeared"] += 1
                    continue
                if ttl >= 0:
                    owners["expiring"] += 1
                    continue
                raw = read(client.getrange, key, 0, 4095)
                if read(client.pttl, key) != -1:
                    owners["changed"] += 1
                    continue
                if len(raw.encode("utf-8") if isinstance(raw, str) else raw) >= 4096:
                    owners["invalid"] += 1
                    continue
                try:
                    state = json.loads(raw)
                    started = state["started_at_ms"]
                    valid = (
                        state.get("schema") == "request-reuse/v1"
                        and state.get("state") == "running"
                        and isinstance(state.get("token"), str)
                        and bool(state["token"])
                        and type(started) is int
                        and 0 < started < 10**15
                    )
                except ValueError, TypeError, KeyError:
                    valid = False
                if not valid:
                    owners["invalid"] += 1
                    continue
                # A new owner can appear during SCAN; compare with a clock read
                # after the record, not with the start of the inspection.
                seconds, microseconds = read(client.time)
                now = int(seconds) * 1000 + int(microseconds) // 1000
                owners["running"] += 1
                age = now - started
                owners["max_age_ms"] = max(owners["max_age_ms"], max(0, age))
                if age < 0 or age >= 120_000:
                    owners["uncertain"] += 1
            if truncated or int(cursor) == 0:
                owners["scan_complete"] = not truncated
                break
        if not owners["scan_complete"]:
            issues.append("owner_scan_incomplete")
        if owners["invalid"]:
            issues.append("invalid_owner_records")
        if owners["uncertain"]:
            issues.append("uncertain_owners")
        report["status"] = (
            "unavailable" if not owners["scan_complete"] else "attention" if issues else "ok"
        )
    except TimeoutError:
        report.update(status="unavailable", issues=["read_deadline"])
    except RedisError, ValueError, TypeError, KeyError, OverflowError:
        report.update(status="unavailable", issues=["redis_read_unavailable"])
    return report


def main() -> int:
    client = None
    report: dict[str, Any]
    try:
        url = os.getenv("FQP_REQUEST_RUNTIME_REDIS_URL", "").strip()
        if not url:
            report = {
                "status": "unavailable",
                "issues": ["runtime_url_missing"],
                "activation_verified": False,
            }
        else:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in ("redis", "rediss")
                or not parsed.hostname
                or not parsed.username
                or not parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError
            client = Redis.from_url(
                url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                retry_on_timeout=False,
                retry=Retry(NoBackoff(), 0),
                max_connections=1,
            )
            report = inspect_redis(client)
    except RedisError, ValueError:
        report = {
            "status": "unavailable",
            "issues": ["runtime_check_unavailable"],
            "activation_verified": False,
        }
    finally:
        if client is not None:
            try:
                client.close()
            except RedisError:
                report = {
                    "status": "unavailable",
                    "issues": ["runtime_check_unavailable"],
                    "activation_verified": False,
                }
    print(json.dumps(report, sort_keys=True))
    return {"ok": 0, "attention": 1, "unavailable": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
