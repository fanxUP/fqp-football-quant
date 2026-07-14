"""Local Scheduler heartbeat shared by the scheduler and health collector."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
HEARTBEAT_PATH = ROOT / ".runtime" / "scheduler_heartbeat.json"
PID_PATH = ROOT / ".runtime" / "scheduler.pid"


def _business_now() -> datetime:
    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    return datetime.now(ZoneInfo(timezone_name))


def _uses_shared_heartbeat() -> bool:
    """Return whether heartbeat freshness replaces local PID validation."""
    return os.getenv("FQP_SCHEDULER_HEARTBEAT_MODE", "local") == "shared"


def write_scheduler_pid(pid: int | None = None) -> int:
    """Atomically record the PID that owns the scheduler heartbeat."""
    owner_pid = pid or os.getpid()
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = PID_PATH.with_suffix(".tmp")
    temp.write_text(str(owner_pid), encoding="utf-8")
    temp.replace(PID_PATH)
    return owner_pid


def clear_scheduler_pid(expected_pid: int) -> bool:
    """Remove the PID file only when it still belongs to this scheduler."""
    try:
        current_pid = int(PID_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if current_pid != expected_pid:
        return False
    PID_PATH.unlink(missing_ok=True)
    return True


def write_heartbeat() -> str:
    """Write an atomic local heartbeat and return its timestamp."""
    timestamp = _business_now().isoformat(timespec="seconds")
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp = HEARTBEAT_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps({"heartbeat_at": timestamp}), encoding="utf-8")
    temp.replace(HEARTBEAT_PATH)
    return timestamp


def is_scheduler_alive(max_age_minutes: int = 5) -> bool:
    """Return whether the latest heartbeat is recent enough."""
    shared_heartbeat = _uses_shared_heartbeat()
    if max_age_minutes < 1 or not HEARTBEAT_PATH.exists():
        return False
    if not shared_heartbeat and not PID_PATH.exists():
        return False
    try:
        if not shared_heartbeat:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
        payload = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        heartbeat = datetime.fromisoformat(payload["heartbeat_at"])
        now = datetime.now(heartbeat.tzinfo) if heartbeat.tzinfo else datetime.now()
        return now - heartbeat <= timedelta(minutes=max_age_minutes)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def get_scheduler_status(max_age_minutes: int = 5) -> dict[str, object | None]:
    """Return diagnostic scheduler state without changing any process state."""
    heartbeat_at: str | None = None
    pid: int | None = None
    if HEARTBEAT_PATH.exists():
        try:
            payload = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
            heartbeat_at = payload.get("heartbeat_at")
        except (OSError, TypeError, json.JSONDecodeError):
            pass
    shared_heartbeat = _uses_shared_heartbeat()
    if PID_PATH.exists() and not shared_heartbeat:
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        except (OSError, TypeError, ValueError):
            pass
    pid_alive = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            pid_alive = True
        except OSError:
            pass
    return {
        "running": is_scheduler_alive(max_age_minutes),
        "heartbeat_at": heartbeat_at,
        "pid": pid,
        "pid_alive": pid_alive,
        "heartbeat_mode": "shared" if shared_heartbeat else "local",
    }
