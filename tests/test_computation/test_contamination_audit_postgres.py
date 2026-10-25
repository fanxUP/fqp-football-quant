"""Audit failures must remain unknown and preserve prior evidence in PostgreSQL."""

import os
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

from scripts.jobs import audit_data_contamination as auditor
from scripts.ops_storage import (
    CONTAMINATION_CHECK_TYPES,
    get_contamination_stats,
    store_contamination_audit,
)


@pytest.fixture
def audit_database(monkeypatch):
    dsn = os.environ.get("FQP_AUDIT_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("set FQP_AUDIT_TEST_DATABASE_URL to a disposable local audit database")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.lstrip("/").startswith("fqp_audit_test_")
    conn = psycopg2.connect(dsn, options="-c statement_timeout=5000 -c lock_timeout=1000")
    schema = f"audit_{uuid4().hex}"
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute(
                (
                    Path(__file__).resolve().parents[2] / "sql/17_operational_health_schema.sql"
                ).read_text()
            )
        conn.autocommit = False
        monkeypatch.setattr(auditor, "get_db", lambda: nullcontext(conn))
        for name in (
            "_check_lineup_temporal_integrity",
            "_check_odds_temporal_integrity",
            "_check_result_leak",
            "_check_feature_snapshot_staleness",
            "_check_prediction_temporal_integrity",
            "_check_error_analysis_scope",
        ):
            monkeypatch.setattr(auditor, name, lambda conn: [])
        yield conn
    finally:
        conn.rollback()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.close()


def record_previous_success(conn, *, age=timedelta(hours=1)):
    at = datetime.now(UTC).replace(tzinfo=None) - age
    for check_type in CONTAMINATION_CHECK_TYPES:
        store_contamination_audit(
            conn,
            {
                "audit_time": at,
                "check_type": check_type,
                "evidence": {"check_status": "passed", "finding_count": 0},
            },
        )
    return at


@pytest.mark.parametrize("failure", ["division_by_zero", "statement_timeout"])
def test_sql_failure_preserves_findings_and_later_checks_recover(
    audit_database, monkeypatch, failure
):
    conn = audit_database
    previous_time = record_previous_success(conn)
    prior_id = store_contamination_audit(
        conn,
        {
            "audit_time": previous_time,
            "check_type": "pre_match_lineup",
            "match_id": 42,
            "contamination_detected": True,
            "severity": "critical",
            "detail": "previous finding",
        },
    )

    def failing_check(connection):
        with connection.cursor() as cur:
            if failure == "statement_timeout":
                cur.execute("SET LOCAL statement_timeout = 25")
                cur.execute("SELECT pg_sleep(0.1)")
            else:
                cur.execute("SELECT 1 / 0")
        return []

    def later_check(connection):
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            assert cur.fetchone() == (1,)
        return []

    monkeypatch.setattr(auditor, "_check_lineup_temporal_integrity", failing_check)
    monkeypatch.setattr(auditor, "_check_odds_temporal_integrity", later_check)

    result = auditor._run_impl()
    stats = get_contamination_stats(conn)

    assert result["status"] == "failed"
    assert result["failed_checks"] == 1
    assert stats["checks_complete"] is False
    assert stats["incomplete_checks"] == 1
    assert stats["failed_checks"] == 1
    assert stats["contamination_found"] == 1
    assert stats["last_successful_audit_time"] == previous_time.isoformat()
    with conn.cursor() as cur:
        cur.execute("SELECT resolved FROM data_contamination_audit_logs WHERE id=%s", (prior_id,))
        assert cur.fetchone() == (False,)

    monkeypatch.setattr(auditor, "_check_lineup_temporal_integrity", later_check)
    recovered = auditor._run_impl()
    stats = get_contamination_stats(conn)
    assert recovered["checks_complete"] is True
    assert stats["checks_complete"] is True
    assert stats["contamination_found"] == 0
    assert stats["last_successful_audit_time"] == stats["latest_audit_time"]


def test_old_or_legacy_clean_records_are_not_a_current_complete_audit(audit_database):
    record_previous_success(audit_database, age=timedelta(hours=31))
    stats = get_contamination_stats(audit_database)
    assert stats["checks_complete"] is False
    assert stats["incomplete_checks"] == 6

    store_contamination_audit(
        audit_database, {"check_type": "pre_match_lineup", "detail": "no issues found"}
    )
    stats = get_contamination_stats(audit_database)
    assert stats["checks_complete"] is False
    assert stats["incomplete_checks"] == 6


def test_partially_persisted_run_does_not_borrow_previous_successes(audit_database):
    record_previous_success(audit_database)
    store_contamination_audit(
        audit_database,
        {
            "check_type": "pre_match_lineup",
            "evidence": {"check_status": "passed"},
        },
    )
    stats = get_contamination_stats(audit_database)
    assert stats["checks_complete"] is False
    assert stats["incomplete_checks"] == 5


def test_result_write_failure_does_not_commit_resolved_old_findings(audit_database, monkeypatch):
    conn = audit_database
    old_id = store_contamination_audit(
        conn,
        {
            "check_type": "pre_match_lineup",
            "match_id": 42,
            "contamination_detected": True,
            "severity": "critical",
        },
    )

    def fail_to_store(*args, **kwargs):
        raise RuntimeError("fixture storage failure")

    monkeypatch.setattr(auditor, "store_contamination_audit", fail_to_store)
    with pytest.raises(RuntimeError, match="fixture storage failure"):
        auditor._run_impl()
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SELECT resolved FROM data_contamination_audit_logs WHERE id=%s", (old_id,))
        assert cur.fetchone() == (False,)
