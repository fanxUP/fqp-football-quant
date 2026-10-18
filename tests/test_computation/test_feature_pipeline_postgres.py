"""Opt-in PostgreSQL contract tests against an explicitly marked empty schema copy."""

from __future__ import annotations

import os
import re
from contextlib import closing
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extensions import parse_dsn

from scripts import feature_importance, feature_storage
from scripts.feature_schema import (
    CURRENT_SNAPSHOT_VERSION,
    FEATURE_COLUMNS,
    SNAPSHOT_READ_COLUMNS,
    SNAPSHOT_WRITE_COLUMNS,
)

MARKER = "fqp-p102-isolated-fixtures/v1"
KICKOFF = datetime(2026, 10, 18, 20)
AT = datetime(2026, 10, 18, 17)


@pytest.fixture(scope="module")
def pg_connect():
    dsn = os.environ.get("FQP_FEATURE_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Dedicated marked feature-contract PostgreSQL was not configured")
    params = parse_dsn(dsn)
    assert params.get("dbname") == "fqp_feature_contract_test"
    assert params.get("host") in ("127.0.0.1", "localhost")
    assert params.get("port", "5432") == "5432"
    assert params.get("user") in ("fqp_feature_test", "fqp")
    assert set(params) <= {"host", "port", "user", "password", "dbname"}

    def connect():
        conn = psycopg2.connect(
            dsn,
            connect_timeout=3,
            options="-c statement_timeout=5000 -c lock_timeout=500 -c application_name=fqp_p102_fixture",
        )
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT current_database(), shobj_description(oid, 'pg_database') "
                    "FROM pg_database WHERE datname=current_database()"
                )
                assert cursor.fetchone() == ("fqp_feature_contract_test", MARKER)
            conn.rollback()
        except BaseException:
            conn.close()
            raise
        return conn

    return connect


@pytest.fixture
def pg(pg_connect):
    with closing(pg_connect()) as conn:
        yield conn


@pytest.fixture
def snapshot(pg):
    tag = uuid4().hex
    with pg.cursor() as cur:
        ids = []
        for side in ("主队", "客队"):
            cur.execute(
                "INSERT INTO teams(team_code, team_name_cn) VALUES (%s,%s) RETURNING id",
                (tag + side, side),
            )
            ids.append(cur.fetchone()[0])
        cur.execute(
            "INSERT INTO competitions(competition_code,competition_type) "
            "VALUES (%s,'league') RETURNING id",
            (tag,),
        )
        competition = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO seasons(season_code,season_name) VALUES (%s,'固定样本赛季') RETURNING id",
            (tag,),
        )
        season = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO competition_seasons(competition_id,season_id) VALUES (%s,%s) RETURNING id",
            (competition, season),
        )
        competition_season = cur.fetchone()[0]
        cur.execute("INSERT INTO stadiums(stadium_name) VALUES ('固定样本球场') RETURNING id")
        stadium = cur.fetchone()[0]
        cur.execute("SELECT nextval('official_matches_id_seq')")
        match_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO official_matches(id,business_date,official_match_code,source_match_id,"
            "league_name,home_team_name,away_team_name,kickoff_time) "
            "VALUES (%s,%s,%s,%s,'固定样本联赛','主队','客队',%s)",
            (
                match_id,
                AT.date() + timedelta(days=match_id // 1000),
                f"周日{match_id % 1000:03}",
                tag,
                KICKOFF,
            ),
        )
    pg.commit()
    values = {column: index + 1 for index, column in enumerate(FEATURE_COLUMNS)}
    values.update(
        match_id=match_id,
        snapshot_time=AT,
        feature_version=CURRENT_SNAPSHOT_VERSION,
        home_team_id=ids[0],
        away_team_id=ids[1],
        competition_season_id=competition_season,
        stadium_id=stadium,
        team_market_value_diff=0,
        home_lineup_confirmed=False,
        away_lineup_confirmed=True,
        home_must_win=False,
        away_must_win=True,
        home_draw_enough=None,
        away_draw_enough=False,
        home_key_absence_count=0,
        precipitation=0,
        wind_speed_10m=None,
        raw_feature_refs={"synthetic": True, "source": "固定响应", "missing": None, "zero": 0},
        unregistered_input="must never become a SQL identifier",
    )
    return values


def test_postgres_schema_matches_existing_feature_contract(pg):
    with pg.cursor() as cur:
        cur.execute(
            "SELECT column_name,data_type FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='match_feature_snapshots'"
        )
        columns = dict(cur.fetchall())
    assert set(SNAPSHOT_READ_COLUMNS) <= columns.keys()
    assert columns["snapshot_time"] == "timestamp without time zone"
    assert columns["home_lineup_confirmed"] == "boolean"
    assert columns["raw_feature_refs"] == "jsonb"
    assert len(FEATURE_COLUMNS) == 55


def test_postgres_full_snapshot_commit_then_read_from_another_connection(pg, pg_connect, snapshot):
    snapshot_id = feature_storage.store_match_feature_snapshot(pg, snapshot)
    with closing(pg_connect()) as reader:
        loaded = feature_storage.load_latest_match_feature_snapshot(
            reader, snapshot["match_id"], as_of=AT
        )
    assert loaded["id"] == snapshot_id
    assert tuple(loaded) == SNAPSHOT_READ_COLUMNS
    for column in SNAPSHOT_WRITE_COLUMNS:
        assert loaded[column] == snapshot[column], column
    assert loaded["home_lineup_confirmed"] is False
    assert loaded["away_lineup_confirmed"] is True
    assert loaded["home_draw_enough"] is None
    assert loaded["precipitation"] == 0
    assert loaded["wind_speed_10m"] is None
    assert "unregistered_input" not in loaded


@pytest.mark.parametrize("flag,number", [(False, 0), (True, 1), (None, None)])
def test_postgres_zero_false_and_missing_remain_distinct(pg, snapshot, flag, number):
    snapshot.update(home_lineup_confirmed=flag, precipitation=number, lineup_strength_diff=number)
    feature_storage.store_match_feature_snapshot(pg, snapshot)
    loaded = feature_storage.load_latest_match_feature_snapshot(pg, snapshot["match_id"], as_of=AT)
    assert loaded["home_lineup_confirmed"] is flag
    assert loaded["precipitation"] == number
    assert loaded["lineup_strength_diff"] == number


def test_postgres_append_only_and_equal_time_latest_id(pg, snapshot):
    first_id = feature_storage.store_match_feature_snapshot(pg, snapshot)
    second_id = feature_storage.store_match_feature_snapshot(pg, {**snapshot, "precipitation": 7})
    assert second_id > first_id
    loaded = feature_storage.load_latest_match_feature_snapshot(pg, snapshot["match_id"], as_of=AT)
    assert loaded["id"] == second_id
    with pg.cursor() as cur:
        cur.execute(
            "SELECT id,precipitation FROM match_feature_snapshots WHERE id IN (%s,%s) ORDER BY id",
            (first_id, second_id),
        )
        assert cur.fetchall() == [(first_id, 0), (second_id, 7)]


@pytest.mark.parametrize("timezone", ["UTC", "Asia/Shanghai"])
def test_postgres_cutoff_and_strict_kickoff_keep_legacy_naive_clock(pg, snapshot, timezone):
    with pg.cursor() as cur:
        cur.execute("SET TIME ZONE %s", (timezone,))
    ids = {}
    for key, timestamp in (
        ("before", AT),
        ("cutoff", AT + timedelta(hours=1)),
        ("future", AT + timedelta(hours=1, minutes=1)),
        ("kickoff", KICKOFF),
        ("after_kickoff", KICKOFF + timedelta(minutes=1)),
    ):
        ids[key] = feature_storage.store_match_feature_snapshot(
            pg, {**snapshot, "snapshot_time": timestamp}
        )
    load = feature_storage.load_latest_match_feature_snapshot
    assert load(pg, snapshot["match_id"], as_of=AT - timedelta(seconds=1)) is None
    assert load(pg, snapshot["match_id"], as_of=AT)["id"] == ids["before"]
    at_cutoff = load(pg, snapshot["match_id"], as_of=AT + timedelta(hours=1))
    assert at_cutoff["id"] == ids["cutoff"]
    assert at_cutoff["snapshot_time"] == AT + timedelta(hours=1)
    assert at_cutoff["snapshot_time"].tzinfo is None
    assert load(pg, snapshot["match_id"], as_of=KICKOFF + timedelta(hours=1))["id"] == ids["future"]


def test_postgres_new_version_does_not_rewrite_legacy_row(pg, snapshot):
    old_time = AT - timedelta(hours=1)
    old_id = feature_storage.store_match_feature_snapshot(
        pg, {**snapshot, "snapshot_time": old_time, "feature_version": "v1_basic"}
    )
    new_id = feature_storage.store_match_feature_snapshot(pg, snapshot)
    load = feature_storage.load_latest_match_feature_snapshot
    assert load(pg, snapshot["match_id"], as_of=old_time)["feature_version"] == "v1_basic"
    assert load(pg, snapshot["match_id"], as_of=AT)["id"] == new_id
    with pg.cursor() as cur:
        cur.execute("SELECT feature_version FROM match_feature_snapshots WHERE id=%s", (old_id,))
        assert cur.fetchone() == ("v1_basic",)


def test_postgres_common_reader_works_in_read_only_transaction(pg, pg_connect, snapshot):
    snapshot_id = feature_storage.store_match_feature_snapshot(pg, snapshot)
    with closing(pg_connect()) as reader:
        reader.set_session(readonly=True)
        assert (
            feature_storage.load_latest_match_feature_snapshot(
                reader, snapshot["match_id"], as_of=AT
            )["id"]
            == snapshot_id
        )
        with reader.cursor() as cur:
            cur.execute("SHOW transaction_read_only")
            assert cur.fetchone() == ("on",)


def test_postgres_confidence_case_keeps_null_separate_from_high(pg):
    capture = MagicMock()
    cursor = capture.cursor.return_value.__enter__.return_value
    cursor.description = []
    cursor.fetchall.return_value = []
    feature_importance.get_condition_performance(capture, dimension="confidence")
    case = re.search(
        r"CASE\s+WHEN mp_home\.confidence_score.*?END AS confidence_range",
        cursor.execute.call_args.args[0],
        re.S,
    )
    assert case is not None
    with pg.cursor() as cur:
        for value, expected in (
            (None, "未校准/未知"),
            (0, "低信心 (<30%)"),
            (0.9, "高信心 (>70%)"),
        ):
            cur.execute(
                f"SELECT {case[0].replace('%', '%%')} "
                "FROM (SELECT %s::numeric AS confidence_score) mp_home",
                (value,),
            )
            assert cur.fetchone() == (expected,)
