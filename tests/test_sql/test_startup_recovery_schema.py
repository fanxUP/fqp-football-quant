from pathlib import Path


def test_startup_recovery_schema_is_durable_and_idempotent() -> None:
    sql = Path("sql/102_startup_recovery_sessions.sql").read_text()

    assert "startup_recovery_sessions" in sql
    assert "startup_recovery_task_runs" in sql
    assert "UNIQUE (boot_id)" in sql
    assert "UNIQUE (idempotency_key)" in sql
    assert "ON DELETE CASCADE" in sql
