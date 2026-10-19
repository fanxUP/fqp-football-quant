"""Opt-in isolated PG16 evidence; no application or provider connection."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg2
import pytest
from psycopg2.extensions import parse_dsn

from scripts.data_contracts import AcquisitionStatus, FactStatus, to_utc
from scripts.feature_storage import get_weather_for_match, store_match_weather_snapshot
from scripts.observation_storage import (
    append_observation,
    capture_observation_cutoff,
    load_observation_as_of,
    record_acquisition_failure,
)

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def connect():
    dsn = os.getenv("FQP_OBSERVATION_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Explicit isolated observation database not configured")
    params = parse_dsn(dsn)
    assert params == dict(
        host="127.0.0.1", port="5432", user="fqp_observation_test", dbname="fqp_observation_test"
    )

    def create():
        conn = psycopg2.connect(
            dsn,
            connect_timeout=3,
            options="-c statement_timeout=5000 -c lock_timeout=500 -c application_name=fqp_p104_fixture",
        )
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT shobj_description(oid,'pg_database') FROM pg_database "
                    "WHERE datname=current_database()"
                )
                assert cur.fetchone() == ("fqp-p104-isolated-fixtures/v1",)
            conn.rollback()
            return conn
        except BaseException:
            conn.close()
            raise

    return create


@pytest.fixture
def pg(connect):
    with closing(connect()) as conn:
        yield conn


@pytest.fixture
def match_id(pg):
    tag = uuid4().hex
    with pg.cursor() as cur:
        cur.execute("SELECT nextval('official_matches_id_seq')")
        mid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO official_matches(id,business_date,official_match_code,source_match_id,"
            "league_name,home_team_name,away_team_name,kickoff_time) "
            "VALUES (%s,%s,%s,%s,'固定联赛','主','客',%s)",
            (
                mid,
                datetime(2026, 10, 20).date() + timedelta(days=mid // 1000),
                f"周二{mid % 1000:03}",
                tag,
                datetime(2026, 10, 20, 20),
            ),
        )
    pg.commit()
    return mid


def stamp(conn, match_id, include_reconstruction=False):
    cutoff = capture_observation_cutoff(
        conn,
        streams=[
            dict(
                match_id=match_id, source_id="open_meteo", domain="weather", subject_key="forecast"
            )
        ],
        include_reconstruction=include_reconstruction,
    )
    conn.commit()
    return cutoff


def write(conn, match_id, **extra):
    acquired = datetime.now(UTC) - timedelta(seconds=1)
    fields = dict(
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        fact_status=FactStatus.VALUE,
        value={"temperature": 0, "confirmed": False, "unknown": None},
        acquired_at=acquired,
        verified_at=acquired,
        effective_at=datetime(2026, 10, 20, 12, tzinfo=UTC),
    )
    fields.update(extra)
    return append_observation(conn, **fields)


def read(conn, match_id, as_of=None, **extra):
    cutoff = as_of or stamp(conn, match_id, extra.pop("include_reconstruction", False))
    return load_observation_as_of(
        conn,
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        cutoff=cutoff,
        **extra,
    )


def test_old_publication_and_acquisition_never_backfill_past(pg, connect, match_id):
    old = datetime(2026, 1, 1, tzinfo=UTC)
    before = stamp(pg, match_id)
    ref = write(pg, match_id, acquired_at=old, verified_at=old, published_at=old)
    pg.commit()
    with closing(connect()) as other:
        assert read(other, match_id, before) is None
        current = read(other, match_id)
        assert current["revision_id"] == ref["revision_id"]
        assert current["available_at"] >= current["ingested_at"] > before.as_of
        assert current["published_at"] == current["first_acquired_at"] == old
        assert current["value"] == {"temperature": 0, "confirmed": False, "unknown": None}


def test_refresh_preserves_original_message_but_revises_freshness(pg, match_id):
    acquired = datetime.now(UTC) - timedelta(seconds=10)
    first = write(
        pg,
        match_id,
        acquired_at=acquired,
        verified_at=acquired,
        valid_until=acquired + timedelta(seconds=1),
    )
    pg.commit()
    original = read(pg, match_id)
    assert original["fact_status"] == "stale"
    cutoff = stamp(pg, match_id)
    second = write(pg, match_id, valid_until=datetime.now(UTC) + timedelta(hours=1))
    pg.commit()
    assert first["revision_id"] == second["revision_id"]
    assert second["check_id"] > first["check_id"]
    assert first["available_at"] == second["available_at"]
    assert read(pg, match_id, cutoff)["fact_status"] == "stale"
    refreshed = read(pg, match_id)
    assert refreshed["fact_status"] == "value"
    assert refreshed["first_acquired_at"] == original["first_acquired_at"]
    assert refreshed["freshness_check_id"] == second["check_id"]


def test_revisions_preserve_a_b_a_and_same_time_source_amendments(pg, match_id):
    refs, cutoffs = [], []
    for content in (1, 2, 1):
        refs.append(write(pg, match_id, value=content))
        pg.commit()
        cutoffs.append(stamp(pg, match_id))
    assert [ref["revision"] for ref in refs] == [1, 2, 3]
    assert refs[0]["content_hash"] == refs[2]["content_hash"]
    for cutoff, ref, value in zip(cutoffs, refs, (1, 2, 1), strict=True):
        loaded = read(pg, match_id, cutoff)
        assert loaded["revision_id"] == ref["revision_id"]
        assert loaded["value"] == value


@pytest.mark.parametrize("status", list(FactStatus))
def test_statuses_do_not_coerce_zero_unknown_or_confirmed_absence(pg, match_id, status):
    write(
        pg,
        match_id,
        fact_status=status,
        value=0 if status == FactStatus.VALUE else None,
        evidence={"coverage_complete": True} if status == FactStatus.CONFIRMED_ABSENT else {},
    )
    pg.commit()
    loaded = read(pg, match_id)
    assert loaded["original_fact_status"] == loaded["fact_status"] == status.value
    assert loaded["value"] == (0 if status == FactStatus.VALUE else None)


@pytest.mark.parametrize("kind", ["candidate", "research_reconstruction"])
def test_nonobserved_evidence_is_never_silently_replayable(pg, match_id, kind):
    ref = write(pg, match_id, evidence_kind=kind)
    pg.commit()
    assert read(pg, match_id)["revision_id"] is None
    research = read(pg, match_id, include_reconstruction=True)
    assert research["revision_id"] == (
        ref["revision_id"] if kind == "research_reconstruction" else None
    )


@pytest.mark.parametrize("status", [s for s in AcquisitionStatus if s != AcquisitionStatus.SUCCESS])
def test_failed_acquisition_preserves_fact_and_has_explicit_status(pg, match_id, status):
    ref = write(pg, match_id)
    pg.commit()
    before = stamp(pg, match_id)
    check = record_acquisition_failure(
        pg,
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        status=status,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    assert read(pg, match_id, before)["acquisition_status"] == "success"
    after = read(pg, match_id)
    assert after["latest_check_id"] == check
    assert after["acquisition_status"] == status.value
    assert after["revision_id"] == ref["revision_id"]
    assert after["original_fact_status"] == "value"


def test_same_stream_concurrent_writes_and_rollback_are_atomic(pg, connect, match_id):
    def append(_):
        with closing(connect()) as conn:
            ref = write(conn, match_id)
            conn.commit()
            return ref

    with ThreadPoolExecutor(max_workers=4) as executor:
        refs = list(executor.map(append, range(4)))
    assert len({ref["revision_id"] for ref in refs}) == 1
    assert len({ref["check_id"] for ref in refs}) == 4
    write(pg, match_id, value=999)
    with closing(connect()) as other:
        assert read(other, match_id)["value"]["temperature"] == 0
    pg.rollback()
    assert read(pg, match_id)["revision_id"] == refs[0]["revision_id"]


@pytest.mark.parametrize("zone", ["UTC", "Asia/Shanghai", "America/New_York"])
def test_cutoff_timezone_is_session_independent_and_future_target_is_visible(pg, match_id, zone):
    ref = write(pg, match_id)
    pg.commit()
    utc_cutoff = stamp(pg, match_id)
    shanghai = utc_cutoff.as_of.astimezone(ZoneInfo("Asia/Shanghai"))
    with pg.cursor() as cur:
        cur.execute("SET TIME ZONE %s", (zone,))
    assert read(pg, match_id, utc_cutoff)["revision_id"] == ref["revision_id"]
    assert (
        read(pg, match_id, replace(utc_cutoff, as_of=shanghai))["revision_id"] == ref["revision_id"]
    )
    assert to_utc(shanghai.replace(tzinfo=None), naive_timezone="Asia/Shanghai") == utc_cutoff.as_of
    assert read(pg, match_id)["effective_at"] > utc_cutoff.as_of


def test_transaction_committing_after_cutoff_never_appears_in_that_replay(pg, connect, match_id):
    write(pg, match_id, value="original")
    pg.commit()
    with closing(connect()) as writer:
        write(writer, match_id, value="delayed commit")
        cutoff = stamp(pg, match_id)
        assert read(pg, match_id, cutoff)["value"] == "original"
        writer.commit()
    assert read(pg, match_id)["value"] == "delayed commit"
    assert read(pg, match_id, cutoff)["value"] == "original"


def test_late_failure_commit_does_not_change_prior_acquisition_status(pg, connect, match_id):
    write(pg, match_id)
    pg.commit()
    with closing(connect()) as writer:
        record_acquisition_failure(
            writer,
            match_id=match_id,
            source_id="open_meteo",
            domain="weather",
            subject_key="forecast",
            status=AcquisitionStatus.FAILED,
            acquired_at=datetime.now(UTC),
        )
        cutoff = stamp(pg, match_id)
        writer.commit()
    assert read(pg, match_id)["acquisition_status"] == "failed"
    assert read(pg, match_id, cutoff)["acquisition_status"] == "success"


def test_future_publication_stays_unavailable(pg, match_id):
    write(pg, match_id, published_at=datetime.now(UTC) + timedelta(days=1))
    pg.commit()
    assert read(pg, match_id) is None


def test_failed_first_acquisition_is_unknown_without_fabricated_fact(pg, match_id):
    record_acquisition_failure(
        pg,
        match_id=match_id,
        source_id="open_meteo",
        domain="weather",
        subject_key="forecast",
        status=AcquisitionStatus.QUOTA_EXHAUSTED,
        acquired_at=datetime.now(UTC),
    )
    pg.commit()
    observed = read(pg, match_id)
    assert observed["fact_status"] == "unknown"
    assert observed["value"] is observed["revision_id"] is None
    assert observed["acquisition_status"] == "quota_exhausted"


def test_cutoff_capture_rejects_a_transaction_with_own_uncommitted_writes(pg, match_id):
    write(pg, match_id)
    with pytest.raises(ValueError, match="before assigning"):
        stamp(pg, match_id)
    pg.rollback()


@pytest.mark.parametrize(
    "table", ["observation_streams", "observation_revisions", "observation_checks"]
)
@pytest.mark.parametrize(
    "operation", ["UPDATE {table} SET id=id", "DELETE FROM {table}", "TRUNCATE {table} CASCADE"]
)
def test_database_enforces_append_only_even_for_owner(pg, match_id, table, operation):
    write(pg, match_id)
    pg.commit()
    with pytest.raises(psycopg2.Error, match="append-only"):
        with pg.cursor() as cur:
            cur.execute(operation.format(table=table))
    pg.rollback()
    assert read(pg, match_id)["value"]["temperature"] == 0


def test_read_only_and_insert_only_roles_are_sufficient(pg, connect, match_id):
    with pg.cursor() as cur:
        cur.execute("SET ROLE fqp_observation_writer")
    ref = write(pg, match_id)
    pg.commit()
    cutoff = stamp(pg, match_id)
    with closing(connect()) as other:
        with other.cursor() as cur:
            cur.execute("SET ROLE fqp_observation_reader")
        assert read(other, match_id, cutoff)["revision_id"] == ref["revision_id"]
        with pytest.raises(psycopg2.Error, match="permission denied"):
            write(other, match_id, value=99)


def weather(match_id, **extra):
    data = dict(
        match_id=match_id,
        snapshot_time=datetime(2026, 10, 18, 20),
        forecast_for_time=datetime(2026, 10, 20, 20),
        temperature_2m=0,
        precipitation=0,
        wind_speed_10m=None,
        raw_json={"fixture": True},
    )
    data.update(extra)
    return data


def test_weather_updates_projection_but_retains_each_known_forecast(pg, connect, match_id):
    first_id = store_match_weather_snapshot(pg, weather(match_id))
    cutoff = stamp(pg, match_id)
    first = read(pg, match_id, cutoff)
    second_id = store_match_weather_snapshot(pg, weather(match_id, temperature_2m=10))
    with closing(connect()) as other:
        assert second_id == first_id
        assert get_weather_for_match(other, match_id)["temperature_2m"] == 10
        assert read(other, match_id, cutoff)["revision_id"] == first["revision_id"]
        assert read(other, match_id)["value"]["temperature_2m"] == 10
        assert read(other, match_id)["revision"] == 2
        assert read(other, match_id)["effective_at"] == datetime(2026, 10, 20, 12, tzinfo=UTC)


def test_legacy_weather_row_is_compatible_but_never_backfilled_as_evidence(pg, match_id):
    with pg.cursor() as cur:
        cur.execute(
            "INSERT INTO match_weather_snapshots(match_id,snapshot_time,forecast_for_time,temperature_2m) "
            "VALUES (%s,%s,%s,22)",
            (match_id, datetime(2026, 1, 1), datetime(2026, 10, 20, 20)),
        )
    pg.commit()
    assert get_weather_for_match(pg, match_id)["temperature_2m"] == 22
    assert read(pg, match_id) is None


@pytest.mark.parametrize("stage", ["projection", "observation"])
def test_weather_projection_and_evidence_failure_roll_back_together(pg, match_id, stage):
    store_match_weather_snapshot(pg, weather(match_id))
    original = read(pg, match_id)
    target = "_store_weather_projection" if stage == "projection" else "append_observation"
    with patch("scripts.feature_storage." + target, side_effect=RuntimeError("fixed failure")):
        with pytest.raises(RuntimeError, match="fixed failure"):
            store_match_weather_snapshot(pg, weather(match_id, temperature_2m=99))
    assert read(pg, match_id)["revision_id"] == original["revision_id"]
    assert get_weather_for_match(pg, match_id)["temperature_2m"] == 0


def test_migration_rerun_and_guarded_down_preserve_existing_history(pg, match_id):
    write(pg, match_id)
    pg.commit()
    original = read(pg, match_id)
    with pg.cursor() as cur:
        cur.execute((ROOT / "sql/107_source_observations.sql").read_text())
    pg.commit()
    assert read(pg, match_id)["revision_id"] == original["revision_id"]
    with pytest.raises(psycopg2.Error, match="retained observations"):
        with pg.cursor() as cur:
            cur.execute((ROOT / "sql/down/107_source_observations.down.sql").read_text())
    pg.rollback()
    assert read(pg, match_id)["revision_id"] == original["revision_id"]
