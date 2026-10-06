from pathlib import Path


def test_scheduler_dropin_enables_explicit_recovery_execution() -> None:
    config = Path("ops/systemd/fqp-scheduler.service.d/10-startup-recovery.conf").read_text()

    assert "[Service]" in config
    assert "Environment=FQP_STARTUP_RECOVERY_MODE=execute" in config
