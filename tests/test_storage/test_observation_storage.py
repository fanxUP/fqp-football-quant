"""Fixed metadata tests; no network or application database."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from scripts.data_contracts import AcquisitionStatus, FactStatus
from scripts.observation_storage import append_observation, record_acquisition_failure

AT = datetime(2026, 10, 18, 8, tzinfo=UTC)


def write(conn, **overrides):
    fields = dict(
        match_id=1,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        fact_status=FactStatus.VALUE,
        value={"temperature": 0, "confirmed": False, "missing": None},
        acquired_at=AT,
        verified_at=AT,
        effective_at=AT + timedelta(hours=8),
    )
    fields.update(overrides)
    return append_observation(conn, **fields)


@pytest.mark.parametrize("field", ["acquired_at", "verified_at", "effective_at", "published_at"])
def test_naive_time_is_never_guessed(field):
    conn = MagicMock()
    with pytest.raises(ValueError, match="aware"):
        write(conn, **{field: AT.replace(tzinfo=None)})
    conn.cursor.assert_not_called()


@pytest.mark.parametrize(
    "fields",
    [
        {"fact_status": FactStatus.VALUE, "value": None},
        {"fact_status": FactStatus.UNKNOWN, "value": 0},
        {"fact_status": FactStatus.CONFIRMED_ABSENT, "value": None},
        {"fact_status": "value"},
        {"source_id": "unregistered_source"},
        {"evidence_kind": "pretend_verified"},
        {"match_id": 0},
        {"subject_key": ""},
        {"domain": "weather'--"},
        {"value": {"invalid": float("nan")}},
        {"value": "x" * 65536},
        {"valid_until": AT - timedelta(seconds=1)},
    ],
)
def test_invalid_facts_fail_before_sql(fields):
    conn = MagicMock()
    with pytest.raises((ValueError, KeyError)):
        write(conn, **fields)
    conn.cursor.assert_not_called()


def test_append_requires_a_caller_owned_transaction():
    conn = MagicMock()
    conn.autocommit = True
    with pytest.raises(ValueError, match="transaction"):
        write(conn)
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("status", [AcquisitionStatus.SUCCESS, "failed"])
def test_failure_receipt_cannot_masquerade_as_success(status):
    conn = MagicMock()
    with pytest.raises(ValueError):
        record_acquisition_failure(
            conn,
            match_id=1,
            source_id="open_meteo",
            domain="weather",
            subject_key="forecast",
            status=status,
            acquired_at=AT,
        )
    conn.cursor.assert_not_called()


@pytest.mark.parametrize("streams", [None, [], [{}] * 129, [None], [{}], [dict(match_id=1)]])
def test_invalid_cutoff_scope_fails_before_sql(streams):
    from scripts.observation_storage import capture_observation_cutoff

    conn = MagicMock()
    with pytest.raises(ValueError):
        capture_observation_cutoff(conn, streams=streams)
    conn.cursor.assert_not_called()
