"""Read-only startup dependency checks for the FQP recovery dry-run."""

from __future__ import annotations

import json
import os
import socket
import sys
from datetime import UTC, datetime
from shutil import disk_usage
from typing import Any
from urllib.parse import urlparse


def evaluate_checks(checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate checks without performing any side effects."""
    normalized: list[dict[str, Any]] = []
    blocking_failures: list[str] = []
    warnings: list[str] = []
    for check in checks:
        name = str(check["name"])
        ok = bool(check.get("ok"))
        blocking = bool(check.get("blocking", False))
        normalized.append(
            {
                "name": name,
                "ok": ok,
                "blocking": blocking,
                "detail": str(check.get("detail", "")),
            }
        )
        if not ok:
            (blocking_failures if blocking else warnings).append(name)

    status = "blocked" if blocking_failures else "degraded" if warnings else "ready"
    return {
        "status": status,
        "checked_at": datetime.now(UTC).isoformat(),
        "checks": normalized,
        "blocking_failures": blocking_failures,
        "warnings": warnings,
    }


def _database_check() -> dict[str, Any]:
    try:
        from apps.backend.src.db import get_db

        with get_db() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return {"name": "postgres", "ok": True, "blocking": True, "detail": "SELECT 1"}
    except Exception as exc:  # noqa: BLE001 - preflight must report the failure, not crash
        return {"name": "postgres", "ok": False, "blocking": True, "detail": str(exc)}


def _redis_check() -> dict[str, Any]:
    target = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    parsed = urlparse(target)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    try:
        with socket.create_connection((host, port), timeout=1.5) as sock:
            sock.sendall(b"*1\r\n$4\r\nPING\r\n")
            response = sock.recv(64)
        ok = response.startswith(b"+PONG")
        return {
            "name": "redis",
            "ok": ok,
            "blocking": True,
            "detail": response.decode("utf-8", errors="replace").strip() or "empty response",
        }
    except (OSError, ValueError) as exc:
        return {"name": "redis", "ok": False, "blocking": True, "detail": str(exc)}


def _disk_check() -> dict[str, Any]:
    try:
        usage = disk_usage("/")
        percent = usage.used / usage.total * 100
        threshold = float(os.getenv("FQP_PREFLIGHT_DISK_MAX_PCT", "85"))
        ok = percent < threshold
        return {
            "name": "disk",
            "ok": ok,
            "blocking": True,
            "detail": f"{percent:.1f}% used (limit {threshold:.1f}%)",
        }
    except (OSError, ValueError) as exc:
        return {"name": "disk", "ok": False, "blocking": True, "detail": str(exc)}


def _clock_check() -> dict[str, Any]:
    """Record a UTC timestamp; NTP policy remains a host-level concern."""
    return {
        "name": "clock",
        "ok": True,
        "blocking": True,
        "detail": datetime.now(UTC).isoformat(),
    }


def _external_dns_check() -> dict[str, Any]:
    host = os.getenv("FQP_PREFLIGHT_DNS_HOST")
    if not host:
        return {"name": "external_api", "ok": True, "blocking": False, "detail": "not configured"}
    try:
        socket.getaddrinfo(host, None)
        return {"name": "external_api", "ok": True, "blocking": False, "detail": host}
    except OSError as exc:
        return {"name": "external_api", "ok": False, "blocking": False, "detail": str(exc)}


def run_preflight() -> dict[str, Any]:
    """Run all safe startup checks and return a JSON-compatible report."""
    return evaluate_checks(
        [_database_check(), _redis_check(), _disk_check(), _clock_check(), _external_dns_check()]
    )


def main() -> int:
    report = run_preflight()
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 1 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    sys.exit(main())
