"""Live service checks shared by health snapshots and API responses."""

from __future__ import annotations

import os
import urllib.request

from scripts.local.scheduler_heartbeat import is_scheduler_alive
from scripts.local.worker_heartbeat import is_worker_alive


def is_http_service_alive(url: str | None = None, timeout_seconds: float = 1.0) -> bool:
    """Probe the configured API health endpoint with a bounded timeout."""
    target = url or os.getenv("FQP_API_HEALTH_URL") or "http://127.0.0.1:8080/health"
    try:
        with urllib.request.urlopen(target, timeout=timeout_seconds) as response:
            return 200 <= int(response.status) < 300
    except OSError, ValueError:
        return False


def get_live_service_status(
    *,
    api_responding: bool | None = None,
    db_responding: bool = True,
) -> dict[str, bool]:
    """Return current liveness rather than the last daily snapshot values."""
    return {
        "scheduler_running": is_scheduler_alive(),
        "worker_running": is_worker_alive(),
        "api_responding": (is_http_service_alive() if api_responding is None else api_responding),
        "db_responding": db_responding,
    }
