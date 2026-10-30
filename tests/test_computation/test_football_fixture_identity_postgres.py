"""Opt-in source identity/membership checks, isolated loopback PostgreSQL only."""

import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.errors import (
    CheckViolation,
    InsufficientPrivilege,
    LockNotAvailable,
    RaiseException,
    UniqueViolation,
)
from psycopg2.extensions import parse_dsn

from scripts.football_pool_catalog import read_pool_catalog, read_pool_catalog_issue
from scripts.official_crawler import parse_traditional_lottery_response
from scripts.official_storage import store_pool_issue, store_pool_issue_matches

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "sql/125_football_fixture_identity.sql"


@pytest.fixture
def database():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN", "")
    if not dsn:
        pytest.skip("explicit isolated history database DSN not supplied")
    params = parse_dsn(dsn)
    assert params.get("host") == "127.0.0.1"
    assert params.get("dbname", "").startswith("fqp_history_test_")
    with closing(psycopg2.connect(dsn)) as conn:
        schema = "identity_" + uuid4().hex
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE model_predictions(id BIGINT PRIMARY KEY)")
            for name in (
                "01_core_official_schema.sql",
                "05_pool_reports_ops_schema.sql",
                "32_official_event_season_targets.sql",
                "117_pool_identity_and_snapshots.sql",
                "124_official_event_season_retention.sql",
            ):
                cur.execute((ROOT / "sql" / name).read_text())
        conn.commit()
        try:
            yield conn
        finally:
            conn.rollback()
            with conn.cursor() as cur:
                cur.execute("RESET ROLE")
                cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
            conn.commit()


def migrate(conn):
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    conn.commit()


@pytest.fixture
def ready(database):
    migrate(database)
    return database


def rows(conn, query, params=()):
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def fixture_row(n=1, **changes):
    raw = dict(infohubMatchId=str(1000 + n), matchId=str(2000 + n))
    row = dict(
        match_order=n,
        source_match_id=str(1000 + n),
        source_ids=raw.copy(),
        raw_json=raw,
        league_name="固定样本联赛",
        home_team_name=f"主{n}",
        away_team_name=f"客{n}",
        kickoff_time="2026-10-30T20:00:00+08:00",
    )
    row.update(changes)
    return row


def put(conn, data, game="t14c", number="26001"):
    issue = store_pool_issue(conn, number, game, None, None, len(data), "unknown", {})
    assert store_pool_issue_matches(conn, issue, data) == len(data)
    return issue


def official(conn, source="9001", code="周五001", league="固定样本联赛"):
    return rows(
        conn,
        """INSERT INTO official_matches(business_date,official_match_code,source_match_id,
            league_name,home_team_name,away_team_name,kickoff_time)
            VALUES ('2026-10-30',%s,%s,%s,'主1','客1','2026-10-30 20:00:00') RETURNING id""",
        (code, source, league),
    )[0][0]


def test_migration_keeps_existing_ids_results_and_saved_plan(database):
    conn = database
    mid = official(conn)
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 14, "unknown", {})
    rows(
        conn,
        "INSERT INTO football_pool_issue_matches(issue_id,match_order,match_id) VALUES (%s,1,%s) RETURNING id",
        (issue, mid),
    )
    rows(
        conn,
        "INSERT INTO official_results(match_id,full_home_goals) VALUES (%s,2) RETURNING id",
        (mid,),
    )
    rows(
        conn,
        """INSERT INTO football_pool_combinations(issue_id,combination_json)
           VALUES (%s,'{"schema_version":"football-pool/v2","snapshot_hash":"old"}') RETURNING id""",
        (issue,),
    )
    conn.commit()
    before = {
        table: rows(conn, f"SELECT * FROM {table}")
        for table in (
            "official_matches",
            "official_results",
            "football_pool_issues",
            "football_pool_combinations",
        )
    }
    migrate(conn)
    assert before == {table: rows(conn, f"SELECT * FROM {table}") for table in before}
    assert rows(
        conn, "SELECT issue_id,match_id,fixture_id,identity_status FROM football_pool_issue_matches"
    ) == [(issue, mid, None, "pending")]
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    # The first explicit refresh preserves even a legacy row's previous FK.
    put(conn, [fixture_row()])
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(2,)]
    assert rows(
        conn,
        "SELECT material_json->>'match_id' FROM football_pool_fixture_revisions ORDER BY id LIMIT 1",
    ) == [(str(mid),)]


def test_all_four_games_keep_memberships_and_share_actual_fixtures_without_fake_jc(ready):
    conn = ready
    mid = official(conn)
    for game, count in (("t14c", 14), ("r9", 14), ("bqc6", 6), ("jq4", 4)):
        put(conn, [fixture_row(n) for n in range(1, count + 1)], game)
    assert rows(
        conn, "SELECT count(*),count(DISTINCT fixture_id) FROM football_pool_fixture_catalog"
    ) == [(38, 14)]
    assert rows(conn, "SELECT count(*) FROM official_matches") == [(1,)]
    assert rows(
        conn,
        "SELECT DISTINCT official_match_id FROM football_pool_fixture_catalog WHERE match_order=1",
    ) == [(mid,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_fixture_catalog WHERE match_order>1 AND official_match_id IS NULL AND identity_status='linked'",
    ) == [(34,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(38,)]


@pytest.mark.parametrize("game,count", [("t14c", 14), ("r9", 14), ("bqc6", 6), ("jq4", 4)])
def test_catalog_reads_each_independent_game_without_jc_or_other_game(ready, game, count):
    conn = ready
    issue = put(conn, [fixture_row(n) for n in range(1, count + 1)], game)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    data = read_pool_catalog(conn, game_type=game)
    assert data["total"] == 1
    header = data["issues"][0]
    assert header["id"] == issue and header["catalogue_complete"] is True
    assert (
        header["stored_matches"] == header["linked_matches"] == header["unique_fixtures"] == count
    )
    assert header["pending_matches"] == header["conflict_matches"] == 0
    assert "raw_json" not in header
    detail = read_pool_catalog_issue(conn, issue)
    assert len(detail["fixtures"]) == count and detail["season_status"] == "pending"
    assert all(f["official_match_id"] is None for f in detail["fixtures"])
    assert all(f["fixture_id"] for f in detail["fixtures"])
    assert rows(conn, "SELECT count(*) FROM official_matches") == [(0,)]


def test_catalog_date_filter_is_beijing_half_open_and_keeps_whole_issue(ready):
    from datetime import date

    conn = ready
    iid = put(
        conn,
        [
            fixture_row(1, kickoff_time="2026-10-30T00:00:00+08:00"),
            fixture_row(2, kickoff_time="2026-10-30T23:59:59+08:00"),
            fixture_row(3, kickoff_time="2026-10-31T00:00:00+08:00"),
        ],
        "bqc6",
    )
    put(
        conn,
        [
            fixture_row(21, kickoff_time="2026-10-29T23:59:59+08:00"),
            fixture_row(22, kickoff_time="2026-10-31T00:00:00+08:00"),
        ],
        "bqc6",
        "26002",
    )
    rows(conn, "SELECT set_config('TimeZone','America/New_York',true)")
    data = read_pool_catalog(conn, date_from=date(2026, 10, 30), date_to=date(2026, 10, 30))
    assert data["total"] == 1 and data["issues"][0]["id"] == iid
    assert data["issues"][0]["stored_matches"] == 3
    detail = read_pool_catalog_issue(conn, iid)
    assert len(detail["fixtures"]) == 3
    assert detail["fixtures"][0]["kickoff"] == "2026-10-30T00:00:00+08:00"
    assert detail["fixtures"][-1]["kickoff"] == "2026-10-31T00:00:00+08:00"
    assert read_pool_catalog(conn, date_from=date(2026, 11, 1))["total"] == 0


def test_catalog_pagination_exact_issue_and_no_double_counted_headers(ready):
    conn = ready
    for game, count in (("t14c", 14), ("r9", 14), ("bqc6", 6), ("jq4", 4)):
        put(conn, [fixture_row(n) for n in range(1, count + 1)], game)
    first = read_pool_catalog(conn, limit=2, offset=0)
    second = read_pool_catalog(conn, limit=2, offset=2)
    assert first["total"] == second["total"] == 4
    assert len({i["id"] for i in first["issues"] + second["issues"]}) == 4
    assert read_pool_catalog(conn, offset=100)["issues"] == []
    assert read_pool_catalog(conn, issue_no="26001")["total"] == 4
    assert read_pool_catalog(conn, issue_no="2600")["total"] == 0
    assert read_pool_catalog(conn, issue_no="' OR true --")["total"] == 0


def test_catalog_preserves_unverified_legacy_missing_identity_and_conflicts(ready):
    conn = ready
    legacy = store_pool_issue(conn, "26001", "bqc6", None, None, 6, "unknown", {})
    rows(
        conn,
        "UPDATE football_pool_issues SET source_game_type=NULL WHERE id=%s RETURNING id",
        (legacy,),
    )
    store_pool_issue_matches(conn, legacy, [fixture_row()])
    pending = put(conn, [fixture_row(2, raw_json={}, source_ids={})], "jq4")
    conflict = put(conn, [fixture_row(3, source_ids={"infohubMatchId": "fake"})], "r9")
    empty = store_pool_issue(conn, "26003", "jq4", None, None, 4, "unknown", {})
    results = {i["id"]: i for i in read_pool_catalog(conn)["issues"]}
    assert results[legacy]["source_verified"] is False
    assert results[pending]["pending_matches"] == 1
    assert results[conflict]["conflict_matches"] == 1
    assert results[empty]["stored_matches"] == 0
    assert all(not h["catalogue_complete"] for h in results.values())
    assert (
        read_pool_catalog_issue(conn, legacy)["fixtures"][0]["identity_reason"]
        == "unverified_game_source"
    )
    assert (
        read_pool_catalog_issue(conn, pending)["fixtures"][0]["identity_reason"]
        == "missing_typed_source_identity"
    )
    assert read_pool_catalog_issue(conn, conflict)["fixtures"][0]["identity_status"] == "conflict"
    assert read_pool_catalog_issue(conn, empty)["fixtures"] == []
    assert read_pool_catalog_issue(conn, 999999) is None


def test_catalog_http_reads_real_schema_with_all_four_game_memberships(ready, client, monkeypatch):
    from contextlib import nullcontext

    from apps.backend.src.routers import pool

    conn = ready
    issue = put(conn, [fixture_row(n) for n in range(1, 5)], "jq4")
    conn.commit()
    monkeypatch.setattr(pool, "get_db", lambda: nullcontext(conn))
    response = client.get("/api/pool/catalog?game_type=jq4&date_from=2026-10-30&date_to=2026-10-30")
    assert response.status_code == 200 and response.json()["total"] == 1
    detail = client.get(f"/api/pool/catalog/{issue}")
    assert detail.status_code == 200 and len(detail.json()["fixtures"]) == 4
    assert detail.json()["issue"]["catalogue_complete"] is True


def test_same_digits_in_traditional_and_jc_namespaces_never_link_different_matches(ready):
    conn = ready
    mid = official(conn, source="1001", league="其他联赛")
    issue = put(conn, [fixture_row()])
    assert rows(
        conn,
        "SELECT match_id,identity_status FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue,),
    ) == [(None, "linked")]
    assert rows(conn, "SELECT id FROM official_matches") == [(mid,)]
    assert rows(conn, "SELECT id_system FROM football_fixture_source_links") == [
        ("traditional.infohubMatchId",),
        ("traditional.t14c.26001.matchId",),
    ]


def test_cross_namespace_exact_bridge_and_timezone_are_session_independent(ready):
    conn = ready
    rows(conn, "SET TIME ZONE 'America/New_York'; SELECT 1")
    official(conn)
    first = fixture_row(source_ids={"matchId": "77"}, raw_json={"matchId": "77"})
    second = fixture_row(
        source_ids={"matchId": "88"},
        raw_json={"matchId": "88"},
        kickoff_time="2026-10-30T12:00:00Z",
    )
    put(conn, [first], "t14c")
    put(conn, [second], "r9")
    assert rows(
        conn,
        "SELECT count(DISTINCT fixture_id),count(DISTINCT match_id),min(kickoff_time) FROM football_pool_issue_matches",
    ) == [(1, 1, datetime(2026, 10, 30, 20))]


def test_traditional_only_cross_game_bridge_requires_exact_identity_not_equal_generic_ids(ready):
    conn = ready
    put(conn, [fixture_row(source_ids={"matchId": "77"}, raw_json={"matchId": "77"})])
    put(conn, [fixture_row(source_ids={"matchId": "88"}, raw_json={"matchId": "88"})], "r9")
    put(
        conn,
        [fixture_row(2, match_order=1, source_ids={"matchId": "77"}, raw_json={"matchId": "77"})],
        "jq4",
    )
    assert rows(
        conn, "SELECT count(*),count(DISTINCT fixture_id) FROM football_pool_fixture_catalog"
    ) == [(3, 2)]
    assert rows(conn, "SELECT count(*) FROM official_matches") == [(0,)]


def test_database_constraints_reject_inconsistent_states_and_duplicate_source_assignment(ready):
    conn = ready
    put(conn, [fixture_row()])
    conn.commit()
    with pytest.raises(CheckViolation):
        rows(conn, "UPDATE football_pool_issue_matches SET fixture_id=NULL RETURNING id")
    conn.rollback()
    with pytest.raises(UniqueViolation):
        rows(
            conn,
            """INSERT INTO football_fixture_source_links
            (source_name,id_system,source_match_id,fixture_id,evidence)
            SELECT source_name,id_system,'different-id',fixture_id,evidence
            FROM football_fixture_source_links LIMIT 1 RETURNING fixture_id""",
        )
    conn.rollback()
    with pytest.raises(RaiseException, match="immutable"):
        rows(conn, "TRUNCATE football_pool_fixture_revisions")
    conn.rollback()


def test_known_source_reschedule_keeps_identity_and_distinct_revisions(ready):
    conn = ready
    issue = put(conn, [fixture_row()])
    fid = rows(conn, "SELECT fixture_id FROM football_pool_issue_matches")[0][0]
    changed = fixture_row(kickoff_time="2026-11-04T20:00:00+08:00")
    put(conn, [changed])
    put(conn, [changed])
    assert rows(
        conn,
        "SELECT fixture_id,kickoff_time FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue,),
    ) == [(fid, datetime(2026, 11, 4, 20))]
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(1,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(2,)]


def test_names_acquired_after_initial_partial_row_remain_protected_after_replacement(ready):
    conn = ready
    put(
        conn,
        [
            fixture_row(
                league_name=None, home_team_name=None, away_team_name=None, kickoff_time=None
            )
        ],
    )
    fid = rows(conn, "SELECT fixture_id FROM football_pool_issue_matches")[0][0]
    put(conn, [fixture_row()])
    put(conn, [fixture_row(2, match_order=1)])
    put(conn, [fixture_row(home_team_name="冲突球队")], "r9")
    assert rows(
        conn,
        "SELECT identity_status,fixture_id FROM football_pool_fixture_catalog WHERE game_type='r9'",
    ) == [("conflict", None)]
    assert rows(
        conn,
        "SELECT fixture_id FROM football_fixture_source_links WHERE id_system='traditional.infohubMatchId' AND source_match_id='1001'",
    ) == [(fid,)]


def test_old_unverified_game_header_does_not_claim_typed_identity(ready):
    conn = ready
    issue = rows(
        conn,
        "INSERT INTO football_pool_issues(game_type,issue_no) VALUES ('t14c','26001') RETURNING id",
    )[0][0]
    store_pool_issue_matches(conn, issue, [fixture_row()])
    assert rows(
        conn, "SELECT identity_status,identity_evidence->>'reason' FROM football_pool_issue_matches"
    ) == [("pending", "unverified_game_source")]
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]


def test_replacement_keeps_old_fixture_and_order_revision(ready):
    conn = ready
    issue = put(conn, [fixture_row()])
    old = rows(conn, "SELECT fixture_id FROM football_pool_issue_matches")[0][0]
    put(conn, [fixture_row(2, match_order=1)])
    current = rows(conn, "SELECT fixture_id FROM football_pool_issue_matches")[0][0]
    assert current != old
    assert rows(
        conn,
        "SELECT fixture_id FROM football_pool_fixture_revisions WHERE issue_id=%s ORDER BY id",
        (issue,),
    ) == [(old,), (current,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(4,)]


@pytest.mark.parametrize(
    "change", ["different_teams", "namespace_collision", "two_bindings", "forged_ids"]
)
def test_conflicts_are_visible_and_never_rebind_sources(ready, change):
    conn = ready
    put(conn, [fixture_row()])
    before = rows(conn, "SELECT * FROM football_fixture_source_links ORDER BY id_system")
    item = fixture_row()
    if change == "different_teams":
        item["home_team_name"] = "另一支球队"
    elif change == "namespace_collision":
        item.update(source_ids={"infohubMatchId": "9999"}, raw_json={"infohubMatchId": "9999"})
    elif change == "two_bindings":
        put(conn, [fixture_row(2, match_order=1)], "r9")
        before = rows(conn, "SELECT * FROM football_fixture_source_links ORDER BY id_system")
        item.update(
            source_ids={"infohubMatchId": "1002", "matchId": "2001"},
            raw_json={"infohubMatchId": "1002", "matchId": "2001"},
        )
    else:
        item["source_ids"] = {"infohubMatchId": "forged"}
    issue = put(conn, [item])
    assert rows(
        conn,
        "SELECT fixture_id,identity_status FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue,),
    ) == [(None, "conflict")]
    assert rows(conn, "SELECT * FROM football_fixture_source_links ORDER BY id_system") == before


def test_ambiguous_jc_and_missing_identity_material_stay_visible(ready):
    conn = ready
    official(conn)
    official(conn, source="9002", code="周五002")
    issue = put(conn, [fixture_row()])
    assert rows(
        conn,
        "SELECT identity_evidence->>'reason' FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue,),
    ) == [("ambiguous_official_identity",)]
    put(conn, [fixture_row(2, source_ids={}, raw_json={}, source_match_id="untyped")], "r9")
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_issue_matches") == [(2,)]


@pytest.mark.parametrize(
    "section,count", [("sfcDetail", 14), ("rjDetail", 14), ("bqcDetail", 6), ("jqcDetail", 4)]
)
def test_actual_parser_output_flows_through_storage_to_shared_catalogue(ready, section, count):
    conn = ready
    raw_rows = [
        dict(
            infohubMatchId=100 + n,
            matchId=200 + n,
            homeTeam=f"主{n}",
            awayTeam=f"客{n}",
            matchName="联赛",
            startTime="2026-10-30 20:00:00",
        )
        for n in range(count)
    ]
    pool = parse_traditional_lottery_response(
        {"value": {section: {"lotteryDrawNum": "26001", "matchList": raw_rows}}}
    )[0]
    put(conn, pool["matches"], pool["game_type"])
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id) FROM football_pool_fixture_catalog WHERE identity_status='linked'",
    ) == [(count, count)]
    assert (
        rows(
            conn, "SELECT source_raw_json FROM football_pool_fixture_catalog ORDER BY match_order"
        )[0][0]
        == raw_rows[0]
    )


def test_unverified_expanded_slots_store_material_without_creating_fixtures(ready):
    conn = ready
    raw_rows = [dict(infohubMatchId=n // 2 + 1, homeTeam="A", awayTeam="B") for n in range(12)]
    pool = parse_traditional_lottery_response(
        {"value": {"bqcDetail": {"lotteryDrawNum": "26001", "matchList": raw_rows}}}
    )[0]
    put(conn, pool["matches"], pool["game_type"])
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(
        conn, "SELECT count(*) FROM football_pool_fixture_catalog WHERE identity_status='pending'"
    ) == [(12,)]


def test_application_role_can_write_memberships_but_not_rewrite_identity_evidence(ready):
    conn = ready
    schema = rows(conn, "SELECT current_schema()")[0][0]
    with conn.cursor() as cur:
        # Same restricted runtime name used by CI; never alter the cluster role.
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            "GRANT SELECT,INSERT,UPDATE ON football_pool_issues,football_pool_issue_matches TO fqp"
        )
        cur.execute("GRANT SELECT ON official_matches TO fqp")
        cur.execute(
            "GRANT USAGE,SELECT ON SEQUENCE football_pool_issues_id_seq,football_pool_issue_matches_id_seq TO fqp"
        )
        cur.execute("SET LOCAL ROLE fqp")
    assert rows(conn, "SELECT rolsuper FROM pg_roles WHERE rolname=current_user") == [(False,)]
    put(conn, [fixture_row()])
    conn.commit()
    for query in (
        "UPDATE football_fixture_source_links SET fixture_id=fixture_id",
        "DELETE FROM football_fixture_source_links",
        "UPDATE football_pool_fixture_revisions SET material_json='{}'",
        "TRUNCATE football_fixtures CASCADE",
    ):
        rows(conn, "SET LOCAL ROLE fqp; SELECT 1")
        with pytest.raises(InsufficientPrivilege):
            rows(conn, query)
        conn.rollback()
    # Even the owning importer cannot silently rewrite the append-only facts.
    with pytest.raises(RaiseException, match="immutable"):
        rows(conn, "DELETE FROM football_fixture_source_links RETURNING fixture_id")
    conn.rollback()


def test_failed_batch_and_explicit_dry_transaction_roll_back_all_identity_work(ready):
    conn = ready
    with pytest.raises(CheckViolation):
        rows(
            conn,
            "ALTER TABLE football_pool_issue_matches ADD CHECK (home_team_name <> '故障'); SELECT 1",
        )
        put(conn, [fixture_row(), fixture_row(2, home_team_name="故障")])
    conn.rollback()
    for table in (
        "football_pool_issues",
        "football_pool_issue_matches",
        "football_fixtures",
        "football_fixture_source_links",
        "football_pool_fixture_revisions",
    ):
        assert rows(conn, f"SELECT count(*) FROM {table}") == [(0,)]
    put(conn, [fixture_row()])
    conn.rollback()
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]


def test_concurrent_game_writers_allocate_one_shared_identity(ready):
    conn = ready
    schema = rows(conn, "SELECT current_schema()")[0][0]
    conn.commit()

    def worker(game):
        with closing(psycopg2.connect(conn.dsn)) as other:
            with other.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cur.execute("SET statement_timeout='5s'")
            put(other, [fixture_row()], game)
            other.commit()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, ("t14c", "r9")))
    assert rows(
        conn, "SELECT count(*),count(DISTINCT fixture_id) FROM football_pool_issue_matches"
    ) == [(2, 1)]


def test_migration_lock_timeout_rolls_back_partial_structure(database):
    conn = database
    schema = rows(conn, "SELECT current_schema()")[0][0]
    conn.commit()
    with closing(psycopg2.connect(conn.dsn)) as locker:
        with locker.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("LOCK TABLE football_pool_issue_matches IN ACCESS EXCLUSIVE MODE")
        with pytest.raises(LockNotAvailable):
            rows(conn, MIGRATION.read_text())
        conn.rollback()
        assert rows(conn, "SELECT to_regclass('football_fixtures')") == [(None,)]
        assert rows(
            conn,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema=%s AND table_name='football_pool_issue_matches' AND column_name='fixture_id'",
            (schema,),
        ) == [(0,)]
        locker.rollback()
