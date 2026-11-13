"""Real SQL regressions for current/history isolation and server pagination."""

from contextlib import contextmanager
from datetime import datetime, timedelta
from os import environ
from unittest.mock import patch
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql

NOW = datetime(2026, 11, 13, 12)


@pytest.fixture
def catalog(client):
    dsn = environ.get("FQP_MATCH_CATALOG_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set a dedicated loopback match-catalog test database URL")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    assert parsed.path.startswith("/fqp_match_catalog_test_")
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    schema = "catalog_" + uuid4().hex
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cur.execute("""CREATE TABLE official_matches (
            id BIGINT PRIMARY KEY, business_date DATE, official_match_code TEXT,
            sport_type TEXT DEFAULT 'football', league_name TEXT, home_team_name TEXT,
            away_team_name TEXT, kickoff_time TIMESTAMP, match_status TEXT,
            raw_json JSONB DEFAULT '{}')""")
        cur.execute("""CREATE TABLE official_results (
            match_id BIGINT PRIMARY KEY, result_status TEXT)""")

    @contextmanager
    def database():
        yield conn

    with patch("apps.backend.src.routers.teams.get_db", database):
        yield client, conn
    with conn.cursor() as cur:
        cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    conn.close()


def add(conn, ident, kickoff, status="scheduled", league="英超", business_date=None):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches
               (id,business_date,official_match_code,league_name,home_team_name,
                away_team_name,kickoff_time,match_status)
               VALUES (%s,%s,'周五001',%s,%s,'客队',%s,%s)""",
            (ident, business_date or kickoff.date(), league, f"主队{ident}", kickoff, status),
        )


def read(client, **params):
    # Freeze the query's business clock without a public time-override parameter.
    with patch("apps.backend.src.services.match_catalog.business_now", return_value=NOW):
        response = client.get("/api/matches/active", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_history_backfill_does_not_change_current_rows_or_counts(catalog):
    client, conn = catalog
    add(conn, 1, NOW + timedelta(hours=2))
    add(conn, 2, NOW - timedelta(hours=14), "Playing")
    add(conn, 3, NOW + timedelta(days=4), business_date=NOW.date())
    before = read(client)
    with conn.cursor() as cur:
        cur.execute("""INSERT INTO official_matches
            (id,business_date,official_match_code,league_name,home_team_name,
             away_team_name,kickoff_time,match_status)
            SELECT n,'2026-10-31','周六001','英超','历史主队','历史客队',
                   '2026-10-31 20:00'::timestamp,'scheduled'
            FROM generate_series(100,700) n""")
    after = read(client)
    assert after == before
    assert after["total"] == 3
    history = read(client, scope="history", date_from="2026-10-31", date_to="2026-10-31", limit=50)
    assert history["total"] == 601
    assert len(history["matches"]) == 50
    assert history["matches"][0]["result_status"] == "missing"
    assert history["matches"][0]["match_status"] == "scheduled"


def test_actual_status_is_preserved_and_missing_result_is_separate(catalog):
    client, conn = catalog
    add(conn, 1, NOW - timedelta(hours=1), "Playing")
    add(conn, 2, NOW - timedelta(hours=2))
    add(conn, 3, NOW - timedelta(hours=3), "Settled")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO official_results VALUES (3,'confirmed')")
    result = read(client)
    by_id = {row["match_id"]: row for row in result["matches"]}
    assert by_id[1]["match_status"] == "Playing"
    assert by_id[2]["match_status"] == "scheduled"
    assert by_id[2]["status_note"] == "开球时间已过，实际状态待核实"
    assert by_id[2]["result_status"] == "missing"
    assert 3 not in by_id


def test_boundary_and_business_day_are_not_confused(catalog):
    client, conn = catalog
    add(conn, 1, NOW - timedelta(hours=48))
    add(conn, 2, NOW - timedelta(hours=48, seconds=1))
    add(conn, 3, NOW + timedelta(hours=15), business_date=NOW.date())
    assert {r["match_id"] for r in read(client)["matches"]} == {1, 3}
    assert read(client, scope="history", date_from="2026-11-11", date_to="2026-11-11")["total"] == 1


def test_filters_sort_counts_and_selection_apply_before_pagination(catalog):
    client, conn = catalog
    for ident in range(1, 64):
        add(conn, ident, NOW + timedelta(minutes=ident), league="中超" if ident == 63 else "英超")
    page = read(client, limit=10, offset=50, sort="desc")
    assert page["total"] == 63
    assert [r["match_id"] for r in page["matches"]] == list(range(13, 3, -1))
    target = read(client, limit=10, selected_id=63)
    assert target["offset"] == 60
    assert target["selected_in_scope"] is True
    filtered = read(client, limit=10, q="主队63", league="中超")
    assert filtered["total"] == 1
    assert filtered["matches"][0]["match_id"] == 63
    hidden = read(client, league="英超", selected_id=63)
    assert hidden["selected_in_scope"] is True
    assert hidden["selected_in_filter"] is False
    assert read(client, limit=10, offset=1000)["offset"] == 60


def test_history_requires_explicit_valid_business_date_range(client):
    with patch(
        "apps.backend.src.routers.teams.get_db",
        side_effect=AssertionError("invalid query must not access DB"),
    ):
        assert client.get("/api/matches/active?scope=history").status_code == 422
        assert (
            client.get(
                "/api/matches/active?scope=history&date_from=2026-10-31&date_to=2026-10-01"
            ).status_code
            == 422
        )


def test_search_is_literal_and_upcoming_summary_does_not_include_started(catalog):
    client, conn = catalog
    add(conn, 1, NOW - timedelta(hours=1))
    add(conn, 2, NOW + timedelta(hours=1))
    assert read(client, q="%")["total"] == 0
    page = read(client, upcoming_only=True, limit=5)
    assert [r["match_id"] for r in page["matches"]] == [2]
    assert page["started_total"] == 1


def test_cancelled_and_confirmed_results_are_archived_without_rewriting_status(catalog):
    client, conn = catalog
    add(conn, 1, NOW + timedelta(hours=1), "Cancelled")
    add(conn, 2, NOW - timedelta(hours=1), "scheduled")
    add(conn, 3, NOW + timedelta(hours=2), None)
    with conn.cursor() as cur:
        cur.execute("INSERT INTO official_results VALUES (2,'confirmed')")
    current = read(client)
    assert [r["match_id"] for r in current["matches"]] == [3]
    assert current["matches"][0]["match_status"] == "unknown"
    history = read(client, scope="history", date_from="2026-11-13", date_to="2026-11-13")
    assert {r["match_id"] for r in history["matches"]} == {1, 2}
    assert next(r for r in history["matches"] if r["match_id"] == 2)["result_status"] == "confirmed"
    assert (
        next(r for r in history["matches"] if r["match_id"] == 2)["status_note"]
        == "已收录确认赛果，来源比赛状态待同步"
    )
