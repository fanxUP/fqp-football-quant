"""Opt-in retention migration/storage/job checks on disposable loopback schemas."""

import json
import os
from contextlib import closing, nullcontext
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.errors import CheckViolation, LockNotAvailable
from psycopg2.extensions import parse_dsn

from scripts import audit_official_history, official_storage
from scripts.jobs import reconcile_event_seasons as reconcile

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "sql/124_official_event_season_retention.sql"


@pytest.fixture
def database():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN", "")
    if not dsn:
        pytest.skip("explicit isolated history database DSN not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_history_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "retention_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE model_predictions(id BIGINT PRIMARY KEY)")
            for name in (
                "01_core_official_schema.sql",
                "05_pool_reports_ops_schema.sql",
                "32_official_event_season_targets.sql",
            ):
                cur.execute((ROOT / "sql" / name).read_text())
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()


def target(season="2025/2026", start="2025-08-01", end="2026-05-31"):
    return dict(
        season_name=season,
        start_date=date.fromisoformat(start),
        end_date=date.fromisoformat(end),
        selection_reason="current_started",
        boundary_source="sporttery",
        source_url="https://example.test/official-season",
        official_league_refs=[{"uniform_league_id": 72}],
        evidence=[{"fixture": True}],
    )


def match(day, source_id, league="联赛"):
    weekday = "一二三四五六日"[date.fromisoformat(day).weekday()]
    return dict(
        business_date=day,
        official_match_code=f"周{weekday}{source_id:03d}",
        source_match_id=str(source_id),
        league_name=league,
        home_team_name="A",
        away_team_name="B",
        kickoff_time=day + "T23:30:00",
    )


def insert_match(conn, day, source_id, league="联赛"):
    row = match(day, source_id, league)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches(business_date,official_match_code,source_match_id,
                league_name,home_team_name,away_team_name,kickoff_time)
                VALUES (%(business_date)s,%(official_match_code)s,%(source_match_id)s,
                    %(league_name)s,%(home_team_name)s,%(away_team_name)s,%(kickoff_time)s)
                RETURNING id""",
            row,
        )
        return cur.fetchone()[0]


def migrate(conn):
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    conn.commit()


def test_migration_seeds_legacy_window_without_changing_existing_ids_and_references(database):
    conn = database
    mid = insert_match(conn, "2022-05-31", 1)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO official_results(match_id,full_home_goals,full_away_goals) VALUES (%s,2,1)",
            (mid,),
        )
        cur.execute(
            "INSERT INTO football_pool_issues(issue_no,game_type) VALUES ('22100','t14c') RETURNING id"
        )
        issue = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO football_pool_issue_matches(issue_id,match_order,match_id) VALUES (%s,1,%s)",
            (issue, mid),
        )
        cur.execute(
            """INSERT INTO official_event_season_targets(league_name,season_name,
                season_start_date,season_end_date,selection_reason,boundary_source,source_url,as_of_date)
                VALUES ('联赛','2025/2026','2025-08-01','2026-05-31',
                    'current_started','sporttery','https://example.test/legacy','2026-01-01')"""
        )
    conn.commit()
    migrate(conn)
    migrate(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT league_name,season_name FROM official_event_season_retention")
        assert cur.fetchall() == [("联赛", "2025/2026")]
        cur.execute("SELECT id FROM official_matches")
        assert cur.fetchall() == [(mid,)]
        cur.execute("SELECT match_id,full_home_goals,full_away_goals FROM official_results")
        assert cur.fetchall() == [(mid, 2, 1)]
        cur.execute("SELECT issue_id,match_id FROM football_pool_issue_matches")
        assert cur.fetchall() == [(issue, mid)]


def test_five_historical_seasons_and_current_can_be_written_and_audited(
    database, monkeypatch, tmp_path
):
    from scripts.official_season_retention import retain_season_windows

    conn = database
    migrate(conn)
    windows = [
        dict(
            target(f"{yr}/{yr + 1}", f"{yr}-08-01", f"{yr + 1}-05-31"),
            league_name="联赛",
            as_of_date=date(2026, 10, 30),
        )
        for yr in range(2021, 2027)
    ]
    retain_season_windows(conn, windows)
    conn.commit()
    data = [match(f"{yr + 1}-05-31", n) for n, yr in enumerate(range(2021, 2027), 1)]
    result = official_storage.store_matches(conn, data)
    assert result == {"inserted": 6, "updated": 0, "errors": []}
    assert official_storage.store_matches(conn, data) == {"inserted": 0, "updated": 6, "errors": []}
    monkeypatch.setattr(audit_official_history, "get_db", lambda: nullcontext(conn))
    (tmp_path / "page.json").write_text(
        json.dumps(
            {
                "response": {
                    "value": {
                        "matchResult": [
                            {
                                "matchId": row["source_match_id"],
                                "matchNumStr": row["official_match_code"],
                                "matchDate": row["business_date"],
                                "leagueAllName": row["league_name"],
                            }
                            for row in data
                        ]
                    }
                }
            }
        )
    )
    audit = audit_official_history.audit_official_history("2021-01-01", "2027-12-31", tmp_path)
    assert audit["matches"] == 6
    assert audit["identity_integrity"] == "ok"
    assert audit["source_completeness"] == "verified_against_official_artifacts"
    assert audit["official_distinct_match_ids"] == 6
    assert audit["missing_database_match_ids"] == 0


@pytest.mark.parametrize("day,league", [("2026-06-01", "联赛"), ("2026-05-31", "未知")])
def test_storage_and_trigger_both_reject_unretained_rows(database, monkeypatch, day, league):
    conn = database
    migrate(conn)
    monkeypatch.setattr(reconcile, "get_db", lambda: nullcontext(conn))
    reconcile._persist_targets(targets={"联赛": target()}, today=date(2026, 1, 1), dry_run=False)
    result = official_storage.store_matches(conn, [match(day, 1, league)])
    assert len(result["errors"]) == 1 and result["inserted"] == 0
    with pytest.raises(CheckViolation, match="outside retained event seasons"):
        insert_match(conn, day, 1, league)
    conn.rollback()


def test_rollover_never_deletes_history_or_references_or_shrinks_prior_window(
    database, monkeypatch
):
    conn = database
    # A pre-existing unknown competition and old-season fixture must survive.
    old = insert_match(conn, "2022-05-31", 1)
    unknown = insert_match(conn, "2026-01-01", 2, "未知")
    with conn.cursor() as cur:
        cur.execute("INSERT INTO official_results(match_id,full_home_goals) VALUES (%s,2)", (old,))
    conn.commit()
    migrate(conn)
    monkeypatch.setattr(reconcile, "get_db", lambda: nullcontext(conn))
    for window in (
        target("2021/2022", "2021-08-01", "2022-05-31"),
        target("2021/2022", "2021-09-01", "2022-04-30"),
        target(),
    ):
        summary = reconcile._persist_targets(
            targets={"联赛": window}, today=date(2026, 1, 1), dry_run=False
        )
    assert summary["matches_deleted"] == 0
    assert summary["matches_outside_retention"] == 1
    assert summary["unresolved_stored_leagues"] == ["未知"]
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM official_matches ORDER BY id")
        assert cur.fetchall() == [(old,), (unknown,)]
        cur.execute("SELECT match_id,full_home_goals FROM official_results")
        assert cur.fetchall() == [(old, 2)]
        cur.execute("SELECT season_name FROM official_event_season_targets")
        assert cur.fetchall() == [("2025/2026",)]
        cur.execute("SELECT count(*) FROM official_event_season_retention")
        assert cur.fetchone() == (3,)
    # A narrower observation must not revoke the previously retained last day.
    insert_match(conn, "2022-05-31", 3)
    conn.commit()


def test_dry_run_and_failed_refresh_leave_both_configurations_unchanged(database, monkeypatch):
    conn = database
    migrate(conn)
    monkeypatch.setattr(reconcile, "get_db", lambda: nullcontext(conn))
    reconcile._persist_targets(targets={"联赛": target()}, today=date(2026, 1, 1), dry_run=True)
    for table in ("official_event_season_targets", "official_event_season_retention"):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            assert cur.fetchone() == (0,)
    # A DB constraint failure after retention insertion must roll back all writes.
    with conn.cursor() as cur:
        cur.execute("ALTER TABLE official_event_season_targets ADD CHECK (league_name <> '故障')")
    conn.commit()
    with pytest.raises(CheckViolation):
        reconcile._persist_targets(
            targets={"联赛": target(), "故障": target()}, today=date(2026, 1, 1), dry_run=False
        )
    # Function must leave a usable connection after its failed transaction.
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM official_event_season_retention")
        assert cur.fetchone() == (0,)


def test_empty_bootstrap_still_accepts_official_fixtures(database):
    conn = database
    migrate(conn)
    assert official_storage.store_matches(conn, [match("2026-05-31", 1)])["inserted"] == 1


def test_each_competition_has_its_own_calendar_and_midnight_uses_business_date(database):
    from scripts.official_season_retention import retain_season_windows

    conn = database
    migrate(conn)
    retain_season_windows(
        conn,
        [
            dict(target(), league_name="跨年制", as_of_date="2026-10-30"),
            dict(
                target("2025", "2025-03-01", "2025-11-30"),
                league_name="自然年制",
                as_of_date="2026-10-30",
            ),
        ],
    )
    conn.commit()
    rows = [
        match("2025-08-01", 1, "跨年制"),
        match("2026-05-31", 2, "跨年制"),
        match("2025-03-01", 3, "自然年制"),
        match("2025-11-30", 4, "自然年制"),
        match("2026-05-31", 5, "自然年制"),
    ]
    # Sale business day can precede kickoff's calendar day. This legacy gate
    # must not silently become a kickoff-date canonical season assignment.
    rows[1]["kickoff_time"] = "2026-06-01T02:00:00"
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'America/New_York'")
    result = official_storage.store_matches(conn, rows)
    assert result["inserted"] == 4
    assert [e["match_code"] for e in result["errors"]] == [rows[4]["official_match_code"]]
    with pytest.raises(CheckViolation):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE official_matches SET business_date='2026-06-01' WHERE source_match_id='2'"
            )
    conn.rollback()


def test_refresh_is_idempotent_and_stale_or_dry_run_cannot_replace_current_selection(
    database, monkeypatch
):
    conn = database
    migrate(conn)
    monkeypatch.setattr(reconcile, "get_db", lambda: nullcontext(conn))
    current = target("2026/2027", "2026-08-01", "2027-05-31")
    for _ in range(2):
        reconcile._persist_targets(
            targets={"联赛": current}, today=date(2026, 10, 30), dry_run=False
        )
    reconcile._persist_targets(targets={"联赛": target()}, today=date(2026, 1, 1), dry_run=False)
    preview = reconcile._persist_targets(
        targets={"联赛": target("2027/2028", "2027-08-01", "2028-05-31")},
        today=date(2027, 10, 30),
        dry_run=True,
    )
    assert preview["retained_window_count"] == 3
    with conn.cursor() as cur:
        cur.execute("SELECT season_name,as_of_date FROM official_event_season_targets")
        assert cur.fetchall() == [("2026/2027", date(2026, 10, 30))]
        cur.execute("SELECT count(*) FROM official_event_season_retention")
        assert cur.fetchone() == (2,)


def test_migration_lock_timeout_rolls_back_new_table_and_keeps_original_gate(database):
    conn = database
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
    conn.commit()
    assert schema.startswith("retention_")
    with closing(psycopg2.connect(conn.dsn)) as locker:
        with locker.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("LOCK TABLE official_event_season_targets IN ACCESS EXCLUSIVE MODE")
        with pytest.raises(LockNotAvailable):
            with conn.cursor() as cur:
                cur.execute(MIGRATION.read_text())
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('official_event_season_retention')")
            assert cur.fetchone() == (None,)
            cur.execute(
                "SELECT pg_get_functiondef('enforce_official_event_season_target()'::regprocedure)"
            )
            assert "outside selected event season" in cur.fetchone()[0]
        locker.rollback()
