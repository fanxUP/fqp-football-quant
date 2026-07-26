from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from scripts.local import worker_heartbeat


def test_worker_heartbeat_reports_recent_and_stale_states(tmp_path):
    path = tmp_path / "worker_heartbeat.json"

    with patch.object(worker_heartbeat, "HEARTBEAT_PATH", path):
        timestamp = worker_heartbeat.write_worker_heartbeat()
        assert timestamp
        assert worker_heartbeat.is_worker_alive() is True

        path.write_text(
            '{"heartbeat_at": "' + (datetime.now(UTC) - timedelta(hours=1)).isoformat() + '"}',
            encoding="utf-8",
        )
        assert worker_heartbeat.is_worker_alive() is False

        path.write_text(
            '{"heartbeat_at": "' + (datetime.now(UTC) + timedelta(hours=1)).isoformat() + '"}',
            encoding="utf-8",
        )
        assert worker_heartbeat.is_worker_alive() is False
