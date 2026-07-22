from __future__ import annotations

from datetime import datetime

from scripts.upset.evidence import evidence_record, stable_payload_hash


def test_evidence_hash_is_stable_across_dictionary_order():
    assert stable_payload_hash({"a": 1, "b": 2}) == stable_payload_hash({"b": 2, "a": 1})


def test_prematch_flag_requires_available_time_before_kickoff():
    kickoff = datetime(2026, 7, 20, 12)

    before = evidence_record(
        event_id=1,
        category="feature",
        code="lineup",
        value={"text": "首发已确认"},
        phase="prematch",
        source_type="feature_snapshot",
        source_reference="feature:9",
        observed_at=datetime(2026, 7, 20, 11),
        available_at=datetime(2026, 7, 20, 11),
        kickoff_time=kickoff,
    )
    after = evidence_record(
        event_id=1,
        category="feature",
        code="lineup",
        value={"text": "赛后才确认"},
        phase="prematch",
        source_type="feature_snapshot",
        source_reference="feature:10",
        observed_at=datetime(2026, 7, 20, 13),
        available_at=datetime(2026, 7, 20, 13),
        kickoff_time=kickoff,
    )

    assert before["available_before_kickoff"] is True
    assert after["available_before_kickoff"] is False
