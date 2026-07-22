from datetime import UTC, datetime, timedelta

from scripts.ops_storage import is_latest_backup_healthy


def test_latest_backup_health_requires_recent_verified_restore():
    healthy = {
        "success": True,
        "integrity_check_passed": True,
        "restore_test_passed": True,
        "started_at": datetime.now(UTC) - timedelta(hours=2),
    }
    assert is_latest_backup_healthy(healthy) is True
    assert is_latest_backup_healthy({**healthy, "restore_test_passed": False}) is False
    assert (
        is_latest_backup_healthy({**healthy, "started_at": datetime.now(UTC) - timedelta(hours=40)})
        is False
    )
