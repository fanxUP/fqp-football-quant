from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from scripts.agents.orchestrator import _now as orchestrator_now
from scripts.jobs.audit_data_contamination import _now as contamination_now
from scripts.jobs.validate_evidence_chain import (
    _business_snapshot_age_seconds,
)
from scripts.jobs.validate_evidence_chain import (
    _now as evidence_now,
)
from scripts.jobs.verify_backup import _now as backup_now
from scripts.local.check_local_environment import _generated_at as environment_generated_at
from scripts.local.snapshot_runtime import _now as runtime_snapshot_now
from scripts.ocr_ticket_parser import _now as ocr_now

SHANGHAI_TIME = datetime(2026, 7, 22, 18, 30, tzinfo=ZoneInfo("Asia/Shanghai"))


def test_persisted_audit_timestamps_use_naive_utc_iso() -> None:
    expected = "2026-07-22T10:30:00"

    assert contamination_now(SHANGHAI_TIME) == expected
    assert evidence_now(SHANGHAI_TIME) == expected
    assert backup_now(SHANGHAI_TIME) == expected
    assert orchestrator_now(SHANGHAI_TIME) == expected
    assert environment_generated_at(SHANGHAI_TIME) == expected
    assert runtime_snapshot_now(SHANGHAI_TIME) == expected
    assert ocr_now(SHANGHAI_TIME) == expected


def test_evidence_snapshot_age_uses_business_clock_for_naive_business_timestamp() -> None:
    snapshot_time = datetime(2026, 7, 22, 17, 45)
    utc_now = datetime(2026, 7, 22, 10, 30, tzinfo=UTC)

    assert _business_snapshot_age_seconds(snapshot_time, now=utc_now) == 45 * 60
