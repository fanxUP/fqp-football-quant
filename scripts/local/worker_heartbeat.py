"""Worker heartbeat used by the local runtime health monitor."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HEARTBEAT_PATH = ROOT / ".runtime" / "worker_heartbeat.json"


def write_worker_heartbeat() -> str:
    """Atomically publish the Worker liveness timestamp."""
    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = HEARTBEAT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps({"heartbeat_at": timestamp}), encoding="utf-8")
    temp.replace(HEARTBEAT_PATH)
    return timestamp


def is_worker_alive(max_age_minutes: int = 5) -> bool:
    """Return whether the Worker published a recent heartbeat."""
    if max_age_minutes < 1 or not HEARTBEAT_PATH.exists():
        return False
    try:
        payload = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(payload["heartbeat_at"])
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        age = datetime.now(UTC) - heartbeat.astimezone(UTC)
        return timedelta(0) <= age <= timedelta(minutes=max_age_minutes)
    except OSError, KeyError, TypeError, ValueError, json.JSONDecodeError:
        return False
