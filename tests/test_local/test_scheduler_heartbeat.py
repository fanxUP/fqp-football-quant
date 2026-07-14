from datetime import datetime, timedelta
from unittest.mock import patch

from scripts.local import scheduler_heartbeat


def test_write_heartbeat_and_read_recent(tmp_path):
    path = tmp_path / "scheduler_heartbeat.json"
    pid_path = tmp_path / "scheduler.pid"
    pid_path.write_text(str(__import__("os").getpid()), encoding="utf-8")
    with patch.object(scheduler_heartbeat, "HEARTBEAT_PATH", path):
        with patch.object(scheduler_heartbeat, "PID_PATH", pid_path):
            timestamp = scheduler_heartbeat.write_heartbeat()
            assert timestamp
            assert scheduler_heartbeat.is_scheduler_alive()


def test_write_heartbeat_uses_business_timezone(tmp_path, monkeypatch):
    path = tmp_path / "scheduler_heartbeat.json"
    monkeypatch.setenv("FQP_TIMEZONE", "Asia/Shanghai")

    with patch.object(scheduler_heartbeat, "HEARTBEAT_PATH", path):
        timestamp = scheduler_heartbeat.write_heartbeat()

    heartbeat = datetime.fromisoformat(timestamp)
    assert heartbeat.tzinfo is not None
    assert heartbeat.utcoffset() == timedelta(hours=8)


def test_old_heartbeat_is_not_alive(tmp_path):
    path = tmp_path / "scheduler_heartbeat.json"
    pid_path = tmp_path / "scheduler.pid"
    pid_path.write_text(str(__import__("os").getpid()), encoding="utf-8")
    path.write_text(
        '{"heartbeat_at": "' + (datetime.now() - timedelta(hours=2)).isoformat() + '"}',
        encoding="utf-8",
    )
    with patch.object(scheduler_heartbeat, "HEARTBEAT_PATH", path), patch.object(scheduler_heartbeat, "PID_PATH", pid_path):
        assert scheduler_heartbeat.is_scheduler_alive() is False


def test_recent_heartbeat_without_scheduler_pid_is_offline(tmp_path):
    path = tmp_path / "scheduler_heartbeat.json"
    with patch.object(scheduler_heartbeat, "HEARTBEAT_PATH", path), patch.object(scheduler_heartbeat, "PID_PATH", tmp_path / "missing.pid"):
        scheduler_heartbeat.write_heartbeat()
        assert scheduler_heartbeat.is_scheduler_alive() is False


def test_shared_heartbeat_does_not_require_cross_container_pid(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "scheduler_heartbeat.json"
    missing_pid = tmp_path / "missing.pid"
    monkeypatch.setenv("FQP_SCHEDULER_HEARTBEAT_MODE", "shared")

    with patch.object(scheduler_heartbeat, "HEARTBEAT_PATH", path), patch.object(
        scheduler_heartbeat,
        "PID_PATH",
        missing_pid,
    ):
        scheduler_heartbeat.write_heartbeat()
        assert scheduler_heartbeat.is_scheduler_alive() is True


def test_scheduler_pid_is_owned_and_only_cleared_by_its_owner(tmp_path):
    pid_path = tmp_path / "scheduler.pid"
    with patch.object(scheduler_heartbeat, "PID_PATH", pid_path):
        assert scheduler_heartbeat.write_scheduler_pid(12345) == 12345
        assert pid_path.read_text(encoding="utf-8") == "12345"
        assert scheduler_heartbeat.clear_scheduler_pid(99999) is False
        assert pid_path.exists()
        assert scheduler_heartbeat.clear_scheduler_pid(12345) is True
        assert not pid_path.exists()
