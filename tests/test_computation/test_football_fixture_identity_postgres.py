"""Opt-in source identity/membership checks, isolated loopback PostgreSQL only."""

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime
from pathlib import Path
from threading import Event
from time import monotonic, sleep
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
from psycopg2.extras import Json

from scripts.football_history_storage import match_history_reference
from scripts.football_pool_catalog import read_pool_catalog, read_pool_catalog_issue
from scripts.official_crawler import parse_traditional_lottery_response
from scripts.official_storage import store_pool_issue, store_pool_issue_matches
from scripts.traditional_history_import import apply_issue_batch, load_issue_batch
from tests.test_jobs.test_traditional_history_import import _write_inputs

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
    with database.cursor() as cur:
        cur.execute(
            "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
        )
        cur.execute((ROOT / "sql/08_season_team_database.sql").read_text())
        cur.execute((ROOT / "sql/127_football_fixture_seasons.sql").read_text())
        cur.execute((ROOT / "sql/128_traditional_history_facts.sql").read_text())
        cur.execute((ROOT / "sql/129_football_fixture_identity_aliases.sql").read_text())
    database.commit()
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
        kickoff_time_precision="minute",
    )
    row.update(changes)
    if row["kickoff_time"] is None and "kickoff_time_precision" not in changes:
        row["kickoff_time_precision"] = "unknown"
    return row


def traditional_history_slot(
    game_type,
    issue_no,
    match_order,
    *,
    full=(3, 2),
    half=(1, 2),
    result_code="3",
    source_match_id=None,
    league_name="英超",
    home_team_name="伯恩利",
    away_team_name="埃弗顿",
    kickoff_date="2022-04-07",
    half_score_source_text=None,
):
    source_game_no = {"t14c": 90, "r9": 90, "bqc6": 98, "jq4": 94}[game_type]
    source_raw = {
        "source": "sporttery_history_api",
        "source_game_no": source_game_no,
        "issue_no": issue_no,
        "match_num": match_order,
        "league_name": league_name,
        "home_team_name": home_team_name,
        "away_team_name": away_team_name,
        "kickoff_date": kickoff_date,
        "kickoff_time_precision": "date_only",
        "full_score_source_text": f"{full[0]}:{full[1]}" if full else "*",
        "half_score_source_text": (
            half_score_source_text
            if half_score_source_text is not None
            else f"{half[0]}:{half[1]}"
            if half
            else ""
        ),
        "product_result_code_source_text": result_code,
        "import_receipt": {
            "contract": "sporttery-traditional-history-import/v1",
            "issue_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "source_row_sha256": "c" * 64,
        },
    }
    row = fixture_row(
        match_order=match_order,
        source_match_id=source_match_id,
        source_ids={},
        raw_json=source_raw,
        league_name=league_name,
        home_team_name=home_team_name,
        away_team_name=away_team_name,
        kickoff_time=None,
        kickoff_date=kickoff_date,
        kickoff_time_precision="date_only",
        source_full_home_goals=full[0] if full is not None else None,
        source_full_away_goals=full[1] if full is not None else None,
        source_half_home_goals=half[0] if half is not None else None,
        source_half_away_goals=half[1] if half is not None else None,
        source_product_result_code=result_code,
        source_result_semantics_key=f"sporttery_game_no_{source_game_no}",
        source_result_source="sporttery_history_api",
        source_result_evidence={"game_no": source_game_no, "match_num": match_order},
        kickoff_evidence={"source": "sporttery_history_api", "date_precision": "date_only"},
    )
    return row


def put(conn, data, game="t14c", number="26001"):
    issue = store_pool_issue(conn, number, game, None, None, len(data), "unknown", {})
    assert store_pool_issue_matches(conn, issue, data) == len(data)
    return issue


def put_traditional_history_slot(conn, game_type, issue_no, match_order, **changes):
    source_game_no = {"t14c": 90, "r9": 90, "bqc6": 98, "jq4": 94}[game_type]
    issue = store_pool_issue(
        conn,
        issue_no,
        game_type,
        None,
        None,
        {"t14c": 14, "r9": 14, "bqc6": 6, "jq4": 4}[game_type],
        "finished",
        {
            "source": "sporttery_history_api",
            "import_receipt": {
                "contract": "sporttery-traditional-history-import/v1",
                "issue_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
            },
        },
        source_game_no=source_game_no,
        source_game_no_source="sporttery_history_api",
    )
    row = traditional_history_slot(game_type, issue_no, match_order, **changes)
    assert store_pool_issue_matches(conn, issue, [row]) == 1
    return issue


def official(conn, source="9001", code="周五001", league="固定样本联赛"):
    return rows(
        conn,
        """INSERT INTO official_matches(business_date,official_match_code,source_match_id,
            league_name,home_team_name,away_team_name,kickoff_time)
            VALUES ('2026-10-30',%s,%s,%s,'主1','客1','2026-10-30 20:00:00') RETURNING id""",
        (code, source, league),
    )[0][0]


def create_valid_fixture_alias(
    conn, source_match_id="9001", issue_no="26001", *, insert_alias=True
):
    official(conn, source=source_match_id)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId',%s,%s,'{}'),
                  ('sporttery','traditional.t14c.'||%s||'.matchOrder','1',%s,'{}')
           RETURNING source_match_id""",
        (source_match_id, canonical, issue_no, alias),
    )
    issue = store_pool_issue(conn, issue_no, "t14c", None, None, 14, "finished", {})
    membership_id = rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias),
    )[0][0]
    if insert_alias:
        rows(
            conn,
            """INSERT INTO football_fixture_identity_aliases
               (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
               VALUES (%s,%s,%s,%s) RETURNING alias_fixture_id""",
            (
                alias,
                canonical,
                source_match_id,
                Json(
                    {
                        "contract": "football-fixture-alias/v1",
                        "basis": "direct_sporttery_match_id",
                        "source_match_id": source_match_id,
                        "candidate_snapshot_sha256": "a" * 64,
                    }
                ),
            ),
        )
    return canonical, alias, issue, membership_id


@pytest.fixture
def history_ready(ready):
    with ready.cursor() as cur:
        cur.execute("INSERT INTO teams(id) VALUES (10),(20)")
        cur.execute((ROOT / "sql/119_football_history_backfill.sql").read_text())
    ready.commit()
    return ready


def history_pair(
    conn,
    *,
    links=None,
    kickoff="2026-10-30T12:00:00Z",
    publish=True,
    competing_fk=False,
    source_season=None,
):
    from psycopg2.extras import Json

    mid = official(conn)
    old_fk = official(conn, source="9002", code="周五002") if competing_fk else None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO official_results(match_id,full_home_goals,full_away_goals,result_status) VALUES (%s,2,1,'confirmed')",
            (mid,),
        )
        cur.execute(
            "INSERT INTO football_history_batches(source_name,content_sha256,normalization_version,manifest) VALUES ('titan007',%s,'fixed/v1','{}') RETURNING id",
            ("a" * 64,),
        )
        bid = cur.fetchone()[0]
        link = dict(
            lottery_match_id=9001,
            home_team="主1",
            home_full_name="主1",
            away_team="客1",
            away_full_name="客1",
            link_type="history2",
        )
        cur.execute(
            """INSERT INTO football_history_matches(batch_id,source_match_id,source_competition_id,kickoff_at,match_status,source_home_team_id,source_away_team_id,home_name,away_name,home_goals,away_goals,source_metadata,official_match_id,source_season) VALUES (%s,5001,36,%s,'finished',10,20,'主1','客1',2,1,%s,%s,%s)""",
            (
                bid,
                kickoff,
                Json(dict(lottery_links=links if links is not None else [link])),
                old_fk,
                source_season,
            ),
        )
        cur.execute(
            "INSERT INTO football_history_records(batch_id,domain,source_record_key,source_match_id,origin,value_json) VALUES (%s,'match_stats','stat',5001,'reported','{"
            + '"home_numeric":0,"away_numeric":null'
            + "}')",
            (bid,),
        )
        if publish:
            cur.execute("UPDATE football_history_batches SET state='published' WHERE id=%s", (bid,))
    conn.commit()
    return mid, bid


def history_season(conn, fid, jc_match_id="9001"):
    from scripts.football_season_identity import import_season
    from tests.test_computation.test_football_season_identity import document, material

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO competitions(competition_code,competition_name_cn,competition_type) VALUES ('premier-league','英格兰超级联赛','league') RETURNING id"
        )
        cid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO seasons(season_code,season_name,start_date,end_date) VALUES ('2026','2026世界杯','2026-03-01','2026-07-19') RETURNING id"
        )
        sid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO competition_seasons(competition_id,season_id) VALUES (%s,%s)",
            (cid, sid),
        )
    data = material()
    data.update(
        members=[dict(fixture_id=fid, jc_match_id=jc_match_id)],
        member_documents=[document(members=(int(jc_match_id),))],
    )
    return import_season(conn, data)


def test_history_reads_explicit_season_as_restricted_readonly_without_rewriting_facts(
    history_ready, monkeypatch
):
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    from apps.backend.src.app import create_app
    from apps.backend.src.routers import football_history
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn)
    fid = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)["fixture_id"]
    expected = history_season(conn, fid)
    before = rows(conn, "SELECT to_jsonb(m) FROM football_history_matches m")
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
        cur.execute("SET TRANSACTION READ ONLY")
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname=current_user")
        assert cur.fetchone() == (False,)
    data = match_history_reference(conn, mid, batch_id=bid)
    season = data["fixture_season"]
    assert data["status"] == "available"
    assert season["fixture_id"] == fid
    assert season["competition_season_id"] == expected["competition_season_id"]
    assert season["competition_code"] == "premier-league"
    assert season["competition_name"] == "英格兰超级联赛"
    assert season["season_code"] == "premier-league:2024-2025"
    assert season["season_name"] == "2024-2025"
    assert str(season["planned_start_date"]) == "2024-08-16"
    assert str(season["planned_end_date"]) == "2025-05-26"
    assert season["source_timezone"] == "Asia/Shanghai"
    assert (season["source_name"], season["source_competition_id"], season["source_season_id"]) == (
        "sporttery",
        "72",
        "11817",
    )
    for key in ("boundary_evidence", "membership_evidence"):
        assert set(season[key]) == {"url", "sha256", "captured_at"}
        assert season[key]["url"].startswith("https://webapi.sporttery.cn/")
        assert len(season[key]["sha256"]) == 64
    # The fixed kickoff is outside the planned window. Explicit membership,
    # rather than the date or legacy World Cup relationship, still wins.
    assert data["source_match"]["season"] is None
    assert rows(conn, "SELECT to_jsonb(m) FROM football_history_matches m") == before
    assert rows(conn, "SHOW transaction_read_only") == [("on",)]

    @contextmanager
    def read_db():
        yield conn

    monkeypatch.setenv("FQP_AUTH_MODE", "none")
    monkeypatch.setattr(football_history, "get_db", read_db)
    response = TestClient(create_app()).get(f"/api/matches/{mid}/history-reference?batch_id={bid}")
    assert response.status_code == 200
    public = response.json()["fixture_season"]
    assert public["planned_start_date"] == "2024-08-16"
    assert public["planned_end_date"] == "2025-05-26"
    assert public["membership_evidence"]["captured_at"] == "2026-10-30T12:00:00+00:00"
    assert rows(conn, "SHOW transaction_read_only") == [("on",)]
    conn.rollback()


@pytest.mark.parametrize("namespace", ["jc.matchId", "uniformMatchId"])
def test_explicit_season_does_not_require_titan_history_and_never_crosses_namespace(
    history_ready, namespace
):
    conn = history_ready
    mid = official(conn)
    fid = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery',%s,'9001',%s,'{}') RETURNING fixture_id",
        (namespace, fid),
    )
    if namespace != "jc.matchId":
        rows(
            conn,
            "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','9003',%s,'{}') RETURNING fixture_id",
            (fid,),
        )
    history_season(conn, fid, "9001" if namespace == "jc.matchId" else "9003")
    conn.commit()
    data = match_history_reference(conn, mid)
    assert data["status"] == "unmatched" and data["rows"] == []
    if namespace == "jc.matchId":
        assert data["fixture_season"]["season_name"] == "2024-2025"
    else:
        assert data["fixture_season"] is None


def test_history_never_promotes_raw_source_season_or_planned_boundaries_to_membership(
    history_ready,
):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn, source_season="2026世界杯")
    link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    # A valid source boundary exists, but only another fixture is a member.
    other = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','9003',%s,'{}') RETURNING fixture_id",
        (other,),
    )
    history_season(conn, other, "9003")
    conn.commit()
    data = match_history_reference(conn, mid)
    assert data["status"] == "available"
    assert data["source_match"]["season"] == "2026世界杯"
    assert data["fixture_season"] is None


def test_history_identity_reads_original_published_facts_and_rolls_back(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn)
    assert match_history_reference(conn, mid)["status"] == "unmatched"
    original = rows(conn, "SELECT * FROM football_history_matches")
    linked = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    assert linked["identity_status"] == "linked"
    data = match_history_reference(conn, mid, batch_id=bid)
    assert data["status"] == "available" and data["source_match"]["id"] == 5001
    assert data["rows"][0]["value"] == dict(home_numeric=0, away_numeric=None)
    assert rows(conn, "SELECT * FROM football_history_matches") == original
    assert link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001) == linked
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(2,)]
    conn.rollback()
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert match_history_reference(conn, mid)["status"] == "unmatched"


@pytest.mark.parametrize(
    "fault", ["time", "names", "result", "multi_jc", "unpublished", "existing_fk"]
)
def test_history_identity_rejects_unproven_pairs_without_writing(history_ready, fault):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    links = [dict(lottery_match_id=9001, home_team="主1", away_team="客1")]
    if fault == "names":
        links[0]["home_team"] = "客1"
    if fault == "multi_jc":
        links.append(dict(lottery_match_id=9002))
    mid, bid = history_pair(
        conn,
        links=links,
        kickoff="2026-10-30T12:15:00Z" if fault == "time" else "2026-10-30T12:00:00Z",
        publish=fault != "unpublished",
        competing_fk=fault == "existing_fk",
    )
    if fault == "result":
        rows(
            conn,
            "UPDATE official_results SET full_home_goals=3 WHERE match_id=%s RETURNING id",
            (mid,),
        )
    result = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    assert result["identity_status"] in {"pending", "conflict"}
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]


def test_history_identity_reuses_traditional_fixture_and_rejects_namespace_collision(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn)
    put(conn, [fixture_row()])
    fixture = rows(conn, "SELECT fixture_id FROM football_pool_fixture_catalog")[0][0]
    linked = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    assert linked["fixture_id"] == fixture
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(1,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(4,)]
    conn.rollback()
    rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")
    fixture = rows(conn, "SELECT id FROM football_fixtures")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','9001',%s,'{}'),('titan007','matchId','9999',%s,'{}') RETURNING fixture_id",
        (fixture, fixture),
    )
    result = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    assert result["identity_status"] == "conflict"
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(2,)]


def test_history_identity_restricted_writer_and_readonly_reader(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            "GRANT SELECT ON official_matches,official_results,football_pool_issue_matches TO fqp"
        )
        # FOR SHARE requires UPDATE on at least one column. Normal production
        # fqp already writes these tables; history remains SELECT-only.
        cur.execute("GRANT UPDATE(kickoff_time) ON official_matches TO fqp")
        cur.execute("GRANT UPDATE(result_status) ON official_results TO fqp")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
    linked = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)
    assert linked["identity_status"] == "linked"
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    assert match_history_reference(conn, mid)["status"] == "available"
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("RESET ROLE")


def test_history_reference_bridge_pins_batches_and_does_not_hide_direct_conflict(history_ready):
    conn = history_ready
    mid, bid = history_pair(conn)
    # Seed only the exact typed identities; similarly named namespaces cannot match.
    fid = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','9001',%s,'{}'),('titan007','matchId','5001',%s,'{}') RETURNING fixture_id",
        (fid, fid),
    )
    assert match_history_reference(conn, mid, batch_id=bid)["status"] == "available"

    with pytest.raises(LookupError):
        match_history_reference(conn, mid, batch_id=bid + 100)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO football_history_batches(source_name,content_sha256,normalization_version,manifest) VALUES ('titan007',%s,'fixed/v1','{}') RETURNING id",
            ("b" * 64,),
        )
        newer = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_history_matches(batch_id,source_match_id,kickoff_at,match_status,source_home_team_id,source_away_team_id,source_metadata,official_match_id) VALUES (%s,5002,'2026-10-30T12:00:00Z','scheduled',10,20,'{}',%s)""",
            (newer, mid),
        )
        cur.execute("UPDATE football_history_batches SET state='published' WHERE id=%s", (newer,))
    data = match_history_reference(conn, mid)
    assert data["status"] == "ambiguous" and data["rows"] == []
    assert match_history_reference(conn, mid, batch_id=bid)["status"] == "available"


@pytest.mark.parametrize(
    ("source", "system", "value", "expected"),
    [
        ("other", "matchId", "5001", "unmatched"),
        ("titan007", "other", "5001", "unmatched"),
        ("titan007", "matchId", "not-a-number", "ambiguous"),
        ("titan007", "matchId", "05001", "ambiguous"),
        ("titan007", "matchId", "9007199254740992", "ambiguous"),
    ],
)
def test_history_reference_typed_ids_never_cross_namespaces_or_cast_bad_values(
    history_ready, source, system, value, expected
):
    conn = history_ready
    mid, _ = history_pair(conn)
    fid = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
        (source_name,id_system,source_match_id,fixture_id,evidence)
        VALUES ('sporttery','jc.matchId','9001',%s,'{}'),(%s,%s,%s,%s,'{}')
        RETURNING fixture_id""",
        (fid, source, system, value, fid),
    )
    data = match_history_reference(conn, mid)
    assert data["status"] == expected and data["rows"] == []


def test_history_reference_shared_identity_uses_latest_or_pinned_single_batch(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, first = history_pair(conn)
    assert (
        link_official_history_fixture(conn, mid, batch_id=first, source_match_id=5001)[
            "identity_status"
        ]
        == "linked"
    )
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO football_history_batches(source_name,content_sha256,normalization_version,manifest) VALUES ('titan007',%s,'fixed/v1','{}') RETURNING id",
            ("b" * 64,),
        )
        second = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_history_matches(batch_id,source_match_id,kickoff_at,match_status,source_home_team_id,source_away_team_id,source_metadata,official_match_id) VALUES (%s,5001,'2026-10-30T12:00:00Z','scheduled',10,20,'{}',%s)""",
            (second, mid),
        )
        cur.execute(
            "INSERT INTO football_history_records(batch_id,domain,source_record_key,source_match_id,origin,value_json) VALUES (%s,'match_stats','new',5001,'reported','{"
            + '"home_numeric":9'
            + "}')",
            (second,),
        )
        cur.execute("UPDATE football_history_batches SET state='published' WHERE id=%s", (second,))
    latest = match_history_reference(conn, mid)
    assert latest["batch"]["id"] == second and latest["total"] == 1
    assert latest["rows"][0]["value"]["home_numeric"] == 9
    pinned = match_history_reference(conn, mid, batch_id=first)
    assert pinned["rows"][0]["value"]["home_numeric"] == 0 and pinned["total"] == 1


def test_history_reference_older_conflict_is_not_hidden_by_two_newer_batches(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, first = history_pair(conn)
    for digest, source, fk, imported in [
        ("b", 5002, mid, "2020-01-01T00:00:00Z"),
        ("c", 5001, None, "2030-01-01T00:00:00Z"),
    ]:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO football_history_batches(source_name,content_sha256,normalization_version,manifest,imported_at) VALUES ('titan007',%s,'fixed/v1','{}',%s) RETURNING id",
                (digest * 64, imported),
            )
            bid = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO football_history_matches(batch_id,source_match_id,kickoff_at,match_status,source_home_team_id,source_away_team_id,source_metadata,official_match_id) VALUES (%s,%s,'2026-10-30T12:00:00Z','scheduled',10,20,'{}',%s)""",
                (bid, source, fk),
            )
            cur.execute("UPDATE football_history_batches SET state='published' WHERE id=%s", (bid,))
    rejected = link_official_history_fixture(conn, mid, batch_id=first, source_match_id=5001)
    assert rejected["identity_status"] == "conflict"
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    # Defensively read even a catalog binding made outside the validated writer.
    fid = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links(source_name,id_system,source_match_id,fixture_id,evidence) VALUES ('sporttery','jc.matchId','9001',%s,'{}'),('titan007','matchId','5001',%s,'{}') RETURNING fixture_id",
        (fid, fid),
    )
    assert match_history_reference(conn, mid)["status"] == "ambiguous"
    assert match_history_reference(conn, mid, batch_id=first)["status"] == "available"


@pytest.mark.parametrize("bad", [0, -1, True, 9007199254740992])
def test_history_identity_invalid_scope_has_no_side_effects(history_ready, bad):
    from scripts.football_fixture_identity import link_official_history_fixture

    with pytest.raises(ValueError):
        link_official_history_fixture(history_ready, bad, batch_id=1, source_match_id=5001)
    assert rows(history_ready, "SELECT count(*) FROM football_fixtures") == [(0,)]


def test_migration_keeps_existing_ids_results_and_saved_plan(database):
    conn = database
    mid = official(conn)
    issue = rows(
        conn,
        """INSERT INTO football_pool_issues(issue_no,game_type,total_matches,official_status)
           VALUES ('26001','t14c',14,'unknown') RETURNING id""",
    )[0][0]
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
    preserved_queries = {
        "official_matches": "SELECT * FROM official_matches",
        "official_results": "SELECT * FROM official_results",
        "football_pool_issues": """SELECT id,issue_no,game_type,sale_start_time,
            sale_stop_time,total_matches,official_status,raw_hash,raw_json
            FROM football_pool_issues""",
        "football_pool_combinations": "SELECT * FROM football_pool_combinations",
    }
    before = {table: rows(conn, query) for table, query in preserved_queries.items()}
    migrate(conn)
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
        )
        cur.execute((ROOT / "sql/128_traditional_history_facts.sql").read_text())
        cur.execute((ROOT / "sql/129_football_fixture_identity_aliases.sql").read_text())
    conn.commit()
    assert before == {table: rows(conn, query) for table, query in preserved_queries.items()}
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


def _seed_traditional_import_fill(conn, tmp_path, live_draw_source=False):
    from scripts.traditional_history_import import MIGRATION

    _register_traditional_import_migration(conn, MIGRATION)

    issue_id = store_pool_issue(
        conn,
        "21062",
        "bqc6",
        "2021-06-02 20:00:00",
        "2021-06-04 22:00:00",
        6,
        "unknown",
        {"legacy": "preserve-header"},
    )
    members = [
        fixture_row(
            order,
            match_order=order,
            home_team_name=f"主队{order}",
            away_team_name=f"客队{order}",
            league_name="国际赛",
            kickoff_time="2021-06-05 00:00:00",
            kickoff_time_precision="unknown",
            source_match_id=None,
            source_ids={},
            raw_json={"legacy": f"preserve-member-{order}"},
            home_win_prob=0.4,
        )
        for order in range(1, 7)
    ]
    store_pool_issue_matches(conn, issue_id, members)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE football_pool_issues SET source_game_type=NULL WHERE id=%s",
            (issue_id,),
        )
        if live_draw_source:
            cur.execute(
                """UPDATE football_pool_issues
                   SET source_game_type='bqc6',source_game_no=98,
                       source_game_no_source='sporttery_live_draw'
                   WHERE id=%s""",
                (issue_id,),
            )
        cur.execute(
            "UPDATE football_pool_issue_matches SET kickoff_date=NULL WHERE issue_id=%s",
            (issue_id,),
        )
        cur.execute(
            "SELECT id,match_id,fixture_id,kickoff_time,home_win_prob "
            "FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order",
            (issue_id,),
        )
        before_members = cur.fetchall()
    conn.commit()

    preview, manifest, summary = _write_inputs(
        tmp_path,
        readiness="candidate_fill_exact_existing_issue",
        production_state="existing_issue_matches_source_api",
    )
    batch = load_issue_batch(preview, manifest, summary, kind="fill", limit=10)
    return issue_id, before_members, batch


def test_date_only_update_preserves_or_archives_prior_precise_kickoff(ready):
    issue_id = put(
        ready,
        [
            fixture_row(
                1,
                kickoff_time="2026-10-30 20:30:00",
                kickoff_date="2026-10-30",
                kickoff_time_precision="minute",
                kickoff_evidence={"source": "minute_schedule", "precision": "minute"},
            )
        ],
    )

    same_date = fixture_row(
        1,
        kickoff_time=None,
        kickoff_date="2026-10-30",
        kickoff_time_precision="date_only",
        kickoff_evidence={"source": "history_api", "precision": "date_only"},
    )
    store_pool_issue_matches(ready, issue_id, [same_date])
    row = rows(
        ready,
        "SELECT kickoff_time::text,kickoff_date::text,kickoff_time_precision,kickoff_evidence "
        "FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0]
    assert row[:3] == ("2026-10-30 20:30:00", "2026-10-30", "minute")
    assert row[3]["source"] == "minute_schedule"
    assert row[3]["source_observations"][-1]["evidence"]["source"] == "history_api"
    store_pool_issue_matches(ready, issue_id, [same_date])
    row = rows(
        ready,
        "SELECT kickoff_evidence FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0][0]
    assert row["source_observations"] == [
        {
            "kickoff_date": "2026-10-30",
            "precision": "date_only",
            "evidence": {"source": "history_api", "precision": "date_only"},
        }
    ]

    changed_date = fixture_row(
        1,
        kickoff_time=None,
        kickoff_date="2026-11-01",
        kickoff_time_precision="date_only",
        kickoff_evidence={"source": "rescheduled_history_api", "precision": "date_only"},
    )
    store_pool_issue_matches(ready, issue_id, [changed_date])
    row = rows(
        ready,
        "SELECT kickoff_time::text,kickoff_date::text,kickoff_time_precision,kickoff_evidence "
        "FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0]
    assert row[:3] == (None, "2026-11-01", "date_only")
    assert row[3]["source"] == "rescheduled_history_api"
    archived = row[3]["superseded_exact_kickoffs"][-1]
    assert archived["kickoff_time"] == "2026-10-30T20:30:00"
    assert archived["evidence"]["source"] == "minute_schedule"
    assert row[3]["source_observations"] == [
        {
            "kickoff_date": "2026-10-30",
            "precision": "date_only",
            "evidence": {"source": "history_api", "precision": "date_only"},
        }
    ]

    store_pool_issue_matches(ready, issue_id, [changed_date])
    refreshed = rows(
        ready,
        "SELECT kickoff_evidence FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0][0]
    assert refreshed["superseded_exact_kickoffs"] == row[3]["superseded_exact_kickoffs"]
    assert refreshed["source_observations"] == row[3]["source_observations"]

    later_date = fixture_row(
        1,
        kickoff_time=None,
        kickoff_date="2026-11-02",
        kickoff_time_precision="date_only",
        kickoff_evidence={"source": "second_reschedule_api", "precision": "date_only"},
    )
    store_pool_issue_matches(ready, issue_id, [later_date])
    row = rows(
        ready,
        "SELECT kickoff_evidence FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0][0]
    assert row["superseded_exact_kickoffs"] == refreshed["superseded_exact_kickoffs"]
    assert row["source_observations"][-1] == {
        "kickoff_date": "2026-11-01",
        "precision": "date_only",
        "evidence": {
            key: value
            for key, value in refreshed.items()
            if key not in {"superseded_exact_kickoffs", "source_observations"}
        },
    }
    assert all(
        "superseded_exact_kickoffs" not in observation["evidence"]
        and "source_observations" not in observation["evidence"]
        for observation in row["source_observations"]
    )
    assert all(
        "superseded_exact_kickoffs" not in archived["evidence"]
        and "source_observations" not in archived["evidence"]
        for archived in row["superseded_exact_kickoffs"]
    )

    store_pool_issue_matches(ready, issue_id, [later_date])
    repeated = rows(
        ready,
        "SELECT kickoff_evidence FROM football_pool_issue_matches WHERE issue_id=%s",
        (issue_id,),
    )[0][0]
    assert repeated == row


def _register_traditional_import_migration(conn, migration):
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS local_schema_migrations("
            "filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
        )
        cur.execute(
            "INSERT INTO local_schema_migrations(filename,checksum_sha256) VALUES (%s,%s)",
            (migration.name, hashlib.sha256(migration.read_bytes()).hexdigest()),
        )
    conn.commit()


def _issue_repair_header(conn, issue_id):
    row = rows(
        conn,
        """SELECT id,game_type,source_game_type,issue_no,total_matches,
                  sale_start_time::text,sale_stop_time::text,md5(raw_json::text),
                  (SELECT count(*) FROM football_pool_combinations c WHERE c.issue_id=i.id)::int,
                  source_game_no,source_game_no_source,raw_json,official_status,
                  prize_pool_estimate::text,raw_hash
           FROM football_pool_issues i WHERE id=%s""",
        (issue_id,),
    )[0]
    return {
        "id": row[0],
        "game_type": row[1],
        "source_game_type": row[2],
        "issue_no": row[3],
        "total_matches": row[4],
        "sale_start_time": row[5],
        "sale_stop_time": row[6],
        "raw_json_md5": row[7],
        "saved_combinations": row[8],
        "source_game_no": row[9],
        "source_game_no_source": row[10],
        "raw_json": row[11],
        "official_status": row[12],
        "prize_pool_estimate": row[13],
        "raw_hash": row[14],
    }


def _issue_repair_members(conn, issue_id):
    return rows(
        conn,
        """SELECT id,match_order,match_id,fixture_id,identity_status,source_match_id,
                  league_name,home_team_name,away_team_name,kickoff_time::text,
                  kickoff_date::text,kickoff_time_precision,kickoff_evidence,
                  source_full_home_goals,source_full_away_goals,
                  source_half_home_goals,source_half_away_goals,
                  source_product_result_code,source_result_semantics_key,
                  source_result_source,source_result_evidence,
                  home_win_prob,draw_prob,away_win_prob,upset_score,
                  public_heat_home,public_heat_draw,public_heat_away,
                  identity_evidence,source_raw_json,md5(source_raw_json::text)
           FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order""",
        (issue_id,),
    )


def _member_repair_document(row):
    return dict(
        membership_id=row[0],
        match_order=row[1],
        match_id=row[2],
        fixture_id=row[3],
        identity_status=row[4],
        source_match_id=row[5],
        league_name=row[6],
        home_team_name=row[7],
        away_team_name=row[8],
        kickoff_time=row[9],
        kickoff_date=row[10],
        kickoff_time_precision=row[11],
        kickoff_evidence=row[12] or {},
        source_full_home_goals=row[13],
        source_full_away_goals=row[14],
        source_half_home_goals=row[15],
        source_half_away_goals=row[16],
        source_product_result_code=row[17],
        source_result_semantics_key=row[18],
        source_result_source=row[19],
        source_result_evidence=row[20] or {},
        home_win_prob=str(row[21]) if row[21] is not None else None,
        draw_prob=str(row[22]) if row[22] is not None else None,
        away_win_prob=str(row[23]) if row[23] is not None else None,
        upset_score=str(row[24]) if row[24] is not None else None,
        public_heat_home=str(row[25]) if row[25] is not None else None,
        public_heat_draw=str(row[26]) if row[26] is not None else None,
        public_heat_away=str(row[27]) if row[27] is not None else None,
        identity_evidence=row[28] or {},
        source_raw_json=row[29] or {},
        source_raw_md5=row[30],
    )


def _seed_legacy_issue_type_repair(
    conn,
    *,
    donor_payload=False,
    donor_conflict=False,
    canonical_invalid_match_link=False,
    reclass_invalid_match_link=False,
):
    from scripts.traditional_history_import import MIGRATION
    from scripts.traditional_history_type_repair import seal_plan

    _register_traditional_import_migration(conn, MIGRATION)
    # Model rows that were created before migration 125 introduced the
    # append-only revision trigger. Keep the trigger enabled during the repair
    # itself so the canonical membership updates still produce revision proof.
    with conn.cursor() as cur:
        cur.execute("DROP TRIGGER record_pool_fixture_revision ON football_pool_issue_matches")
    operations = []
    donor_ids = {}
    canonical_id = None
    canonical_members = None
    official_ids = {}
    for issue_num in range(26127, 26152):
        issue_no = str(issue_num)
        donor_id = store_pool_issue(
            conn,
            issue_no,
            "bqc6",
            "2026-10-25 20:00:00",
            "2026-10-27 17:30:00",
            14,
            "closed",
            {"legacy_issue": issue_no},
        )
        donor_ids[issue_no] = donor_id
        rows(
            conn,
            "UPDATE football_pool_issues SET source_game_type=NULL WHERE id=%s RETURNING id",
            (donor_id,),
        )
        donor_members = []
        for order in range(1, 15):
            match_id = None
            if issue_no == "26151" and order <= 10:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO official_matches(business_date,official_match_code,source_match_id,
                            league_name,home_team_name,away_team_name,kickoff_time)
                            VALUES ('2026-10-27',%s,%s,'固定联赛',%s,%s,'2026-10-27 00:00:00') RETURNING id""",
                        (f"周二{order:03d}", f"200000{order}", f"主{order}", f"客{order}"),
                    )
                    official_match_id = cur.fetchone()[0]
                    official_ids[order] = official_match_id
                    if not canonical_invalid_match_link:
                        match_id = official_match_id
            donor_payload_fields = {}
            if issue_no == "26151" and order == 1 and donor_payload:
                donor_payload_fields = {
                    "home_win_prob": 0.67,
                    "public_heat_home": 0.21,
                    "source_full_home_goals": 2,
                    "source_product_result_code": "2",
                    "source_result_semantics_key": "sporttery_game_no_90",
                    "source_result_source": "sporttery_history_api",
                    "source_result_evidence": {"source": "legacy_api", "result": "2"},
                }
            donor_members.append(
                fixture_row(
                    order,
                    match_order=order,
                    home_team_name=f"主{order}",
                    away_team_name=f"客{order}",
                    league_name="固定联赛",
                    kickoff_time="2026-10-27 00:00:00",
                    source_match_id=None,
                    match_id=match_id,
                    raw_json={"legacy_member": f"{issue_no}/{order}"},
                    **donor_payload_fields,
                )
            )
        store_pool_issue_matches(conn, donor_id, donor_members)
        if issue_no == "26127" and reclass_invalid_match_link:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO official_matches(
                           business_date,official_match_code,source_match_id,
                           league_name,home_team_name,away_team_name,kickoff_time
                       ) VALUES ('2026-10-27','周二999','reclass-bad-26127',
                           '固定联赛','错误主队','客1','2026-10-27 00:00:00')
                       RETURNING id"""
                )
                wrong_official_id = cur.fetchone()[0]
            rows(
                conn,
                "UPDATE football_pool_issue_matches SET match_id=%s "
                "WHERE issue_id=%s AND match_order=1 RETURNING id",
                (wrong_official_id, donor_id),
            )
        if issue_no == "26151" and not canonical_invalid_match_link:
            # The legacy bqc6 header lacks a trusted source type, so the normal
            # writer correctly refuses to attach matches. These IDs model the
            # already existing, independently audited production references.
            with conn.cursor() as cur:
                cur.executemany(
                    "UPDATE football_pool_issue_matches SET match_id=%s "
                    "WHERE issue_id=%s AND match_order=%s",
                    [(official_ids[order], donor_id, order) for order in range(1, 11)],
                )
        donor_header = _issue_repair_header(conn, donor_id)
        donor_roster = [
            _member_repair_document(row) for row in _issue_repair_members(conn, donor_id)
        ]
        source_roster = [
            {
                "match_order": order,
                "home_team_name": f"主{order}",
                "away_team_name": f"客{order}",
                "kickoff_date": "2026-10-27",
            }
            for order in range(1, 15)
        ]
        if issue_no == "26151":
            canonical_id = store_pool_issue(
                conn,
                issue_no,
                "t14c",
                "2026-10-25 20:00:00",
                "2026-10-27 17:30:00",
                14,
                "closed",
                {"canonical_issue": issue_no},
            )
            rows(
                conn,
                "UPDATE football_pool_issues SET source_game_type='t14c' WHERE id=%s RETURNING id",
                (canonical_id,),
            )
            # Seed the canonical slots as pre-125 rows without running identity
            # resolution: otherwise the helper would discover and attach the
            # donor's exact official-match links before the merge is exercised.
            with conn.cursor() as cur:
                cur.executemany(
                    """INSERT INTO football_pool_issue_matches
                        (issue_id,match_order,league_name,home_team_name,away_team_name,
                         kickoff_time,kickoff_date,kickoff_time_precision,home_win_prob,
                         public_heat_home,source_raw_json)
                       VALUES (%s,%s,'固定联赛',%s,%s,'2026-10-27 00:00:00',
                               '2026-10-27','minute',%s,%s,
                               jsonb_build_object('canonical_member',%s))""",
                    [
                        (
                            canonical_id,
                            order,
                            f"主{order}",
                            f"客{order}",
                            (
                                0.44
                                if issue_no == "26151" and order == 1 and donor_conflict
                                else None
                                if issue_no == "26151" and order == 1 and donor_payload
                                else 0.42
                            ),
                            None,
                            str(order),
                        )
                        for order in range(1, 15)
                    ],
                )
            if canonical_invalid_match_link:
                rows(
                    conn,
                    "UPDATE football_pool_issue_matches SET match_id=%s "
                    "WHERE issue_id=%s AND match_order=1 RETURNING id",
                    (official_ids[2], canonical_id),
                )
            canonical_members = [
                _member_repair_document(row) for row in _issue_repair_members(conn, canonical_id)
            ]
            operations.append(
                {
                    "operation": "merge_duplicate_into_canonical",
                    "issue_no": issue_no,
                    "legacy_issue_id": donor_id,
                    "canonical_issue_id": canonical_id,
                    "source_game_no": 90,
                    "source_game_no_source": "sporttery_history_api",
                    "expected_legacy_header": donor_header,
                    "expected_canonical_header": _issue_repair_header(conn, canonical_id),
                    "expected_legacy_roster": donor_roster,
                    "expected_canonical_roster": canonical_members,
                    "expected_source_roster": source_roster,
                }
            )
        else:
            operations.append(
                {
                    "operation": "reclassify_header",
                    "issue_no": issue_no,
                    "legacy_issue_id": donor_id,
                    "source_game_no": 90,
                    "source_game_no_source": "sporttery_history_api",
                    "expected_legacy_header": donor_header,
                    "expected_legacy_roster": donor_roster,
                    "expected_source_roster": source_roster,
                }
            )
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TRIGGER record_pool_fixture_revision AFTER INSERT OR UPDATE "
            "ON football_pool_issue_matches FOR EACH ROW "
            "EXECUTE FUNCTION record_pool_fixture_revision()"
        )
    conn.commit()
    plan = seal_plan(
        {
            "contract": "sporttery-legacy-pool-issue-type-repair/v2",
            "member_snapshot_schema": "football-pool-issue-member/v2",
            "source_server_sha": "b49a0e44aeddb1cf0d174642c70f4826ac57178f",
            "source_inventory_sha256": "a" * 64,
            "source_preview_sha256": "b" * 64,
            "issues": operations,
        }
    )
    return plan, donor_ids, canonical_id, canonical_members, official_ids


def test_legacy_type_repair_preserves_issue_ids_and_transfers_match_links(ready):
    from scripts.traditional_history_import import MIGRATION
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, canonical_id, canonical_members, official_ids = _seed_legacy_issue_type_repair(
        conn
    )

    result = apply_issue_type_repair(conn, plan)
    conn.commit()

    assert result == {
        "reclassified_issues": 24,
        "merged_duplicate_issues": 1,
        "deleted_duplicate_members": 14,
        "transferred_match_links": 10,
        "already_repaired_issues": 0,
    }
    assert rows(
        conn,
        "SELECT id,game_type,source_game_type,source_game_no,source_game_no_source "
        "FROM football_pool_issues WHERE issue_no='26127'",
    ) == [(donor_ids["26127"], "t14c", "t14c", 90, "sporttery_history_api")]
    assert rows(
        conn,
        "SELECT id,game_type,source_game_type FROM football_pool_issues WHERE issue_no='26151'",
    ) == [(canonical_id, "t14c", "t14c")]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issues WHERE game_type='bqc6' AND issue_no BETWEEN '26127' AND '26151'",
    ) == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches WHERE issue_id=%s",
        (donor_ids["26127"],),
    ) == [(14,)]
    assert [
        row[0]
        for row in rows(
            conn,
            "SELECT id FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order",
            (canonical_id,),
        )
    ] == [row["membership_id"] for row in canonical_members]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches WHERE issue_id=%s AND match_id IS NOT NULL",
        (canonical_id,),
    ) == [(10,)]
    assert rows(conn, "SELECT count(*) FROM official_matches") == [(10,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches WHERE issue_id=%s AND home_win_prob=0.42",
        (canonical_id,),
    ) == [(14,)]
    assert rows(
        conn,
        "SELECT raw_json->'legacy_issue_type_repair'->>'plan_sha256' FROM football_pool_issues WHERE id=%s",
        (canonical_id,),
    ) == [(plan["plan_sha256"],)]
    assert set(official_ids.values()) == {
        row[0]
        for row in rows(
            conn,
            "SELECT match_id FROM football_pool_issue_matches WHERE issue_id=%s AND match_id IS NOT NULL",
            (canonical_id,),
        )
    }

    conn.commit()
    repeated = apply_issue_type_repair(conn, plan)
    conn.commit()
    assert repeated == {
        "reclassified_issues": 0,
        "merged_duplicate_issues": 0,
        "deleted_duplicate_members": 0,
        "transferred_match_links": 0,
        "already_repaired_issues": 25,
    }
    assert MIGRATION.exists()


def test_legacy_type_repair_transfers_and_archives_donor_payload(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, _, canonical_id, _, _ = _seed_legacy_issue_type_repair(conn, donor_payload=True)

    apply_issue_type_repair(conn, plan)
    conn.commit()

    merged = rows(
        conn,
        """SELECT home_win_prob,public_heat_home,source_full_home_goals,
                  source_product_result_code,source_result_evidence,source_raw_json
           FROM football_pool_issue_matches WHERE issue_id=%s AND match_order=1""",
        (canonical_id,),
    )[0]
    assert (float(merged[0]), float(merged[1]), *merged[2:4]) == (0.67, 0.21, 2, "2")
    assert merged[4] == {"source": "legacy_api", "result": "2"}
    preserved = merged[5]["legacy_issue_type_repair"]["preserved_donor_member"]
    assert float(preserved["home_win_prob"]) == 0.67
    assert preserved["source_full_home_goals"] == 2
    assert preserved["source_raw_json"] == {"legacy_member": "26151/1"}


def test_legacy_type_repair_refuses_conflicting_donor_model_values(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(
        conn, donor_payload=True, donor_conflict=True
    )

    with pytest.raises(ValueError, match="conflicting home_win_prob"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()
    assert rows(
        conn,
        "SELECT game_type FROM football_pool_issues WHERE id=%s",
        (donor_ids["26151"],),
    ) == [("bqc6",)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches WHERE issue_id=%s",
        (donor_ids["26151"],),
    ) == [(14,)]


def test_legacy_type_repair_rejects_invalid_canonical_only_match_link(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, canonical_id, _, official_ids = _seed_legacy_issue_type_repair(
        conn, canonical_invalid_match_link=True
    )
    conn.commit()

    with pytest.raises(ValueError, match="official-match link differs from its slot identity"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()
    assert rows(
        conn,
        "SELECT game_type FROM football_pool_issues WHERE id=%s",
        (donor_ids["26151"],),
    ) == [("bqc6",)]
    assert rows(
        conn,
        "SELECT match_id FROM football_pool_issue_matches WHERE issue_id=%s AND match_order=1",
        (donor_ids["26151"],),
    ) == [(None,)]
    assert rows(
        conn,
        "SELECT match_id FROM football_pool_issue_matches WHERE issue_id=%s AND match_order=1",
        (canonical_id,),
    ) == [(official_ids[2],)]


def test_legacy_type_repair_rejects_invalid_reclassification_match_link(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(conn, reclass_invalid_match_link=True)
    issue_id = donor_ids["26127"]

    with pytest.raises(ValueError, match="official-match link differs from its slot identity"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()
    assert rows(
        conn,
        "SELECT game_type FROM football_pool_issues WHERE id=%s",
        (issue_id,),
    ) == [("bqc6",)]
    assert (
        rows(
            conn,
            "SELECT match_id FROM football_pool_issue_matches WHERE issue_id=%s AND match_order=1",
            (issue_id,),
        )[0][0]
        is not None
    )


def test_legacy_type_repair_uses_old_kickoff_date_when_migration_column_is_empty(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair, seal_plan

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(conn)
    issue_id = donor_ids["26127"]
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches(
                   business_date,official_match_code,source_match_id,league_name,
                   home_team_name,away_team_name,kickoff_time
               ) VALUES ('2026-10-26','周一998','legacy-26127-slot1','固定联赛',
                         '主1','客1','2026-10-27 00:45:00') RETURNING id"""
        )
        official_match_id = cur.fetchone()[0]
        cur.execute(
            """UPDATE football_pool_issue_matches
               SET match_id=%s,kickoff_date=NULL,kickoff_time_precision='unknown'
               WHERE issue_id=%s AND match_order=1""",
            (official_match_id, issue_id),
        )

    operation = next(issue for issue in plan["issues"] if issue["issue_no"] == "26127")
    operation["expected_legacy_roster"] = [
        _member_repair_document(row) for row in _issue_repair_members(conn, issue_id)
    ]
    plan = seal_plan(plan)
    conn.commit()

    result = apply_issue_type_repair(conn, plan)
    conn.commit()

    assert result["reclassified_issues"] == 24
    assert rows(
        conn,
        "SELECT game_type,source_game_no FROM football_pool_issues WHERE id=%s",
        (issue_id,),
    ) == [("t14c", 90)]


def test_legacy_type_repair_rejects_changed_archived_donor_receipt(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, _, canonical_id, _, _ = _seed_legacy_issue_type_repair(conn)
    apply_issue_type_repair(conn, plan)
    conn.commit()
    rows(
        conn,
        """UPDATE football_pool_issue_matches
           SET source_raw_json=jsonb_set(source_raw_json,
             '{legacy_issue_type_repair,preserved_donor_member,home_team_name}',
             '"tampered"'::jsonb)
           WHERE issue_id=%s AND match_order=1 RETURNING id""",
        (canonical_id,),
    )
    conn.commit()

    with pytest.raises(ValueError, match="canonical member state changed after repair"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()


def test_legacy_type_repair_rejects_post_merge_canonical_member_drift(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, _, canonical_id, _, _ = _seed_legacy_issue_type_repair(conn)
    apply_issue_type_repair(conn, plan)
    conn.commit()
    rows(
        conn,
        "UPDATE football_pool_issue_matches SET home_win_prob=0.41 "
        "WHERE issue_id=%s AND match_order=2 RETURNING id",
        (canonical_id,),
    )
    conn.commit()

    with pytest.raises(ValueError, match="canonical member state changed after repair"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()


def test_legacy_type_repair_rejects_post_reclass_header_drift(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(conn)
    apply_issue_type_repair(conn, plan)
    conn.commit()
    rows(
        conn,
        "UPDATE football_pool_issues SET official_status='tampered' WHERE id=%s RETURNING id",
        (donor_ids["26127"],),
    )
    conn.commit()

    with pytest.raises(ValueError, match="repaired header field official_status changed"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()


def test_legacy_type_repair_aborts_entire_batch_on_stale_roster(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair, seal_plan

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(conn)
    tampered = dict(plan)
    tampered["issues"] = [dict(issue) for issue in plan["issues"]]
    tampered["issues"][10]["expected_legacy_roster"] = [
        dict(member) for member in tampered["issues"][10]["expected_legacy_roster"]
    ]
    tampered["issues"][10]["expected_legacy_roster"][0]["home_team_name"] = "来源变化"
    tampered = seal_plan({key: value for key, value in tampered.items() if key != "plan_sha256"})

    with pytest.raises(ValueError, match="roster differs"):
        apply_issue_type_repair(conn, tampered)
    conn.rollback()
    assert rows(
        conn,
        "SELECT game_type FROM football_pool_issues WHERE id=%s",
        (donor_ids["26127"],),
    ) == [("bqc6",)]
    assert rows(conn, "SELECT count(*) FROM official_matches") == [(10,)]


def test_legacy_type_duplicate_merge_refuses_saved_combinations(ready):
    from scripts.traditional_history_type_repair import apply_issue_type_repair

    conn = ready
    plan, donor_ids, _, _, _ = _seed_legacy_issue_type_repair(conn)
    rows(
        conn,
        "INSERT INTO football_pool_combinations(issue_id,combination_json) VALUES (%s,'{}') RETURNING id",
        (donor_ids["26151"],),
    )
    conn.commit()

    with pytest.raises(ValueError, match="saved combinations"):
        apply_issue_type_repair(conn, plan)
    conn.rollback()
    assert rows(
        conn,
        "SELECT game_type FROM football_pool_issues WHERE id=%s",
        (donor_ids["26127"],),
    ) == [("bqc6",)]


def test_traditional_new_import_inserts_and_rejects_changed_receipt_content(ready, tmp_path):
    from scripts.traditional_history_import import MIGRATION

    conn = ready
    _register_traditional_import_migration(conn, MIGRATION)
    preview, manifest, summary = _write_inputs(tmp_path)
    batch = load_issue_batch(preview, manifest, summary, kind="new", limit=10)

    first = apply_issue_batch(conn, batch)
    conn.commit()
    assert first == {"inserted_issues": 1, "inserted_members": 6, "already_imported_issues": 0}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,source_game_type,source_game_no,source_game_no_source,total_matches "
            "FROM football_pool_issues WHERE game_type='bqc6' AND issue_no='21062'"
        )
        header = cur.fetchone()
        cur.execute(
            """SELECT id,match_order,match_id,fixture_id,kickoff_time,kickoff_date,
                      kickoff_time_precision,source_full_home_goals,source_product_result_code
               FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order""",
            (header[0],),
        )
        members = cur.fetchall()
    assert header[1:] == ("bqc6", 98, "sporttery_history_api", 6)
    assert len(members) == 6
    assert [member[1] for member in members] == list(range(1, 7))
    assert all(member[2:5] == (None, None, None) for member in members)
    assert all(member[5].isoformat() == "2021-06-05" for member in members)
    assert all(member[6] == "date_only" for member in members)
    assert members[0][7:] == (None, "*,*")

    conn.commit()
    repeated = apply_issue_batch(conn, batch)
    conn.commit()
    assert repeated == {"inserted_issues": 0, "inserted_members": 0, "already_imported_issues": 1}

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE football_pool_issue_matches SET home_win_prob=0.5 "
            "WHERE issue_id=%s AND match_order=2",
            (header[0],),
        )
    conn.commit()
    with pytest.raises(ValueError, match="members were modified"):
        apply_issue_batch(conn, batch)
    conn.rollback()


@pytest.mark.parametrize("drift", ("raw_json", "raw_hash"))
def test_traditional_new_import_rejects_issue_header_evidence_drift(ready, tmp_path, drift):
    from scripts.traditional_history_import import MIGRATION, _pool_raw_hash

    conn = ready
    _register_traditional_import_migration(conn, MIGRATION)
    preview, manifest, summary = _write_inputs(tmp_path)
    batch = load_issue_batch(preview, manifest, summary, kind="new", limit=10)
    apply_issue_batch(conn, batch)
    conn.commit()
    issue = batch["issues"][0]
    issue_id = rows(
        conn,
        "SELECT id FROM football_pool_issues WHERE game_type=%s AND issue_no=%s",
        (issue["game_type"], issue["issue_no"]),
    )[0][0]
    if drift == "raw_json":
        changed_raw = dict(issue["raw_json"])
        changed_raw["unexpected_header_evidence"] = "changed"
        changed_hash = _pool_raw_hash(changed_raw)
    else:
        changed_raw = issue["raw_json"]
        changed_hash = "0" * 32
    rows(
        conn,
        "UPDATE football_pool_issues SET raw_json=%s,raw_hash=%s WHERE id=%s RETURNING id",
        (Json(changed_raw), changed_hash, issue_id),
    )
    conn.commit()

    with pytest.raises(ValueError, match="header was modified"):
        apply_issue_batch(conn, batch)
    conn.rollback()


def test_traditional_fill_preserves_legacy_ids_links_and_probabilities(ready, tmp_path):
    conn = ready
    issue_id, before_members, batch = _seed_traditional_import_fill(conn, tmp_path)

    result = apply_issue_batch(conn, batch)
    conn.commit()
    repeated = apply_issue_batch(conn, batch)
    conn.commit()

    assert result == {"filled_issues": 1, "filled_members": 6, "already_filled_issues": 0}
    assert repeated == {"filled_issues": 0, "filled_members": 0, "already_filled_issues": 1}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,source_game_type,source_game_no,source_game_no_source,raw_json->>'legacy' "
            "FROM football_pool_issues WHERE id=%s",
            (issue_id,),
        )
        assert cur.fetchone() == (
            issue_id,
            "bqc6",
            98,
            "sporttery_history_api",
            "preserve-header",
        )
        cur.execute(
            """SELECT id,match_id,fixture_id,kickoff_time,kickoff_date,
                      kickoff_time_precision,home_win_prob,source_match_id,
                      source_full_home_goals,source_product_result_code,
                      source_raw_json->>'legacy'
               FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order""",
            (issue_id,),
        )
        after = cur.fetchall()
    for original, updated in zip(before_members, after, strict=True):
        assert updated[:4] == original[:4]
        assert updated[4].isoformat() == "2021-06-05"
        assert updated[5] == "date_only"
        assert float(updated[6]) == float(original[4])
        assert updated[10].startswith("preserve-member-")
    assert after[0][8] is None and after[0][9] == "*,*"
    assert after[1][8] == 0 and after[1][9] == "1,0"


def test_traditional_fill_adds_history_to_live_draw_issue_without_replacing_origin(ready, tmp_path):
    conn = ready
    issue_id, before_members, batch = _seed_traditional_import_fill(
        conn, tmp_path, live_draw_source=True
    )

    result = apply_issue_batch(conn, batch)
    conn.commit()
    repeated = apply_issue_batch(conn, batch)
    conn.commit()

    assert result == {"filled_issues": 1, "filled_members": 6, "already_filled_issues": 0}
    assert repeated == {"filled_issues": 0, "filled_members": 0, "already_filled_issues": 1}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source_game_no,source_game_no_source,raw_json "
            "FROM football_pool_issues WHERE id=%s",
            (issue_id,),
        )
        game_no, source_namespace, raw = cur.fetchone()
        cur.execute(
            """SELECT id,match_id,fixture_id,kickoff_time,home_win_prob,
                      source_full_home_goals,source_product_result_code,
                      source_result_source,source_raw_json->>'legacy'
               FROM football_pool_issue_matches WHERE issue_id=%s ORDER BY match_order""",
            (issue_id,),
        )
        after = cur.fetchall()
    assert (game_no, source_namespace) == (98, "sporttery_live_draw")
    marker = raw["traditional_history_import"]
    assert marker["evidence"]["source"] == "sporttery_history_api"
    assert marker["receipt"]["contract"] == "sporttery-traditional-history-import/v1"
    for original, updated in zip(before_members, after, strict=True):
        assert updated[:4] == original[:4]
        assert float(updated[4]) == float(original[4])
        assert updated[8].startswith("preserve-member-")
        assert updated[7] == "sporttery_history_api"


@pytest.mark.parametrize("drift", ("raw_json", "raw_hash", "prize_pool_estimate"))
def test_traditional_fill_rejects_issue_header_evidence_drift(ready, tmp_path, drift):
    from scripts.traditional_history_import import _pool_raw_hash

    conn = ready
    issue_id, _, batch = _seed_traditional_import_fill(conn, tmp_path)
    apply_issue_batch(conn, batch)
    conn.commit()
    (raw,) = rows(conn, "SELECT raw_json FROM football_pool_issues WHERE id=%s", (issue_id,))[0]
    if drift == "raw_json":
        raw = dict(raw)
        raw["unexpected_header_evidence"] = "changed"
        raw_hash = _pool_raw_hash(raw)
    elif drift == "prize_pool_estimate":
        raw_hash = _pool_raw_hash(raw)
        rows(
            conn,
            "UPDATE football_pool_issues SET prize_pool_estimate=100 WHERE id=%s RETURNING id",
            (issue_id,),
        )
    else:
        raw_hash = "0" * 32
    if drift != "prize_pool_estimate":
        rows(
            conn,
            "UPDATE football_pool_issues SET raw_json=%s,raw_hash=%s WHERE id=%s RETURNING id",
            (Json(raw), raw_hash, issue_id),
        )
    conn.commit()

    with pytest.raises(ValueError, match="header was modified after import"):
        apply_issue_batch(conn, batch)
    conn.rollback()


def test_traditional_fill_rechecks_all_slots_before_any_write(ready, tmp_path):
    conn = ready
    issue_id, _, batch = _seed_traditional_import_fill(conn, tmp_path)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE football_pool_issue_matches SET away_team_name='changed' "
            "WHERE issue_id=%s AND match_order=6",
            (issue_id,),
        )
    conn.commit()

    with pytest.raises(ValueError, match="away team differs"):
        apply_issue_batch(conn, batch)
    conn.rollback()
    assert rows(
        conn,
        "SELECT source_game_no FROM football_pool_issues WHERE id=%s",
        (issue_id,),
    ) == [(None,)]


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


def test_fixture_alias_projects_canonical_fixture_and_official_match_without_changing_rows(ready):
    conn = ready
    mid = official(conn)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,%s),
                  ('sporttery','traditional.t14c.26001.matchOrder','1',%s,%s)
           RETURNING source_match_id""",
        (
            canonical,
            Json({"home_team_name": "主1", "away_team_name": "客1"}),
            alias,
            Json({"home_team_name": "主1", "away_team_name": "客1"}),
        ),
    )
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 1, "finished", {})
    rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias),
    )
    before_rows = rows(conn, "SELECT count(*) FROM football_pool_fixture_catalog")

    rows(
        conn,
        """INSERT INTO football_fixture_identity_aliases
           (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
           VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
        (
            alias,
            canonical,
            Json(
                {
                    "contract": "football-fixture-alias/v1",
                    "basis": "direct_sporttery_match_id",
                    "source_match_id": "9001",
                    "candidate_snapshot_sha256": "a" * 64,
                }
            ),
        ),
    )

    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_catalog") == before_rows
    detail = read_pool_catalog_issue(conn, issue)
    assert detail["fixtures"][0]["fixture_id"] == canonical
    assert detail["fixtures"][0]["official_match_id"] == mid


def test_fixture_alias_rejects_mismatched_official_identity_and_alias_chains(ready):
    conn = ready
    official(conn, source="9001", code="周五001")
    official(conn, source="9002", code="周五002")
    canonical1 = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    canonical2 = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias1 = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias2 = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,'{}'),
                  ('sporttery','jc.matchId','9002',%s,'{}'),
                  ('sporttery','traditional.t14c.26001.matchOrder','1',%s,'{}'),
                  ('sporttery','traditional.t14c.26001.matchOrder','2',%s,'{}')
           RETURNING source_match_id""",
        (canonical1, canonical2, alias1, alias2),
    )
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 1, "finished", {})
    rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias1),
    )
    conn.commit()
    evidence = Json(
        {
            "contract": "football-fixture-alias/v1",
            "basis": "direct_sporttery_match_id",
            "source_match_id": "9001",
            "candidate_snapshot_sha256": "a" * 64,
        }
    )
    with pytest.raises(RaiseException, match="canonical|MatchId"):
        rows(
            conn,
            """INSERT INTO football_fixture_identity_aliases
               (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
               VALUES (%s,%s,'9002',%s) RETURNING alias_fixture_id""",
            (alias1, canonical1, evidence),
        )
    conn.rollback()
    rows(
        conn,
        """INSERT INTO football_fixture_identity_aliases
           (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
           VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
        (alias1, canonical1, evidence),
    )
    with pytest.raises(RaiseException, match="chain|alias"):
        rows(
            conn,
            """INSERT INTO football_fixture_identity_aliases
               (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
               VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
            (alias2, alias1, evidence),
        )
    conn.rollback()


def test_fixture_alias_requires_every_match_order_link_to_match_an_exact_pool_slot(ready):
    conn = ready
    official(conn)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,'{}'),
                  ('sporttery','traditional.t14c.26001.matchOrder','2',%s,'{}')
           RETURNING source_match_id""",
        (canonical, alias),
    )
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 1, "finished", {})
    rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias),
    )

    with pytest.raises(RaiseException, match="exact traditional issue slot"):
        rows(
            conn,
            """INSERT INTO football_fixture_identity_aliases
               (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
               VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
            (
                alias,
                canonical,
                Json(
                    {
                        "contract": "football-fixture-alias/v1",
                        "basis": "direct_sporttery_match_id",
                        "source_match_id": "9001",
                        "candidate_snapshot_sha256": "a" * 64,
                    }
                ),
            ),
        )
    conn.rollback()


def test_alias_fixture_identity_rows_cannot_change_after_alias_creation(ready):
    conn = ready
    canonical, alias, issue, membership_id = create_valid_fixture_alias(conn)
    next_issue = store_pool_issue(conn, "26002", "t14c", None, None, 14, "finished", {})
    conn.commit()

    with pytest.raises(RaiseException, match="aliased fixture cannot be changed"):
        rows(
            conn,
            """INSERT INTO football_fixture_source_links
               (source_name,id_system,source_match_id,fixture_id,evidence)
               VALUES ('titan007','matchId','5001',%s,'{}') RETURNING fixture_id""",
            (alias,),
        )
    conn.rollback()

    with pytest.raises(RaiseException, match="aliased fixture cannot be changed"):
        rows(
            conn,
            """INSERT INTO football_pool_issue_matches
               (issue_id,match_order,league_name,home_team_name,away_team_name,
                source_result_source,fixture_id,identity_status,identity_evidence)
               VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
               RETURNING id""",
            (next_issue, alias),
        )
    conn.rollback()

    with pytest.raises(RaiseException, match="aliased fixture cannot be changed"):
        rows(
            conn,
            "UPDATE football_pool_issue_matches SET fixture_id=%s WHERE id=%s RETURNING id",
            (canonical, membership_id),
        )
    conn.rollback()

    with pytest.raises(RaiseException, match="aliased fixture cannot be changed"):
        rows(
            conn,
            "DELETE FROM football_pool_issue_matches WHERE id=%s RETURNING id",
            (membership_id,),
        )
    conn.rollback()

    with pytest.raises(RaiseException, match="issue namespace used by an aliased fixture"):
        rows(
            conn,
            "UPDATE football_pool_issues SET issue_no='26003' WHERE id=%s RETURNING id",
            (issue,),
        )
    conn.rollback()

    assert rows(
        conn,
        "SELECT fixture_id,identity_status FROM football_pool_issue_matches WHERE id=%s",
        (membership_id,),
    ) == [(alias, "linked")]
    assert rows(
        conn,
        "SELECT count(*) FROM football_fixture_source_links WHERE fixture_id=%s",
        (alias,),
    ) == [(1,)]


def test_alias_fixture_cannot_acquire_a_season_membership_after_creation(ready):
    conn = ready
    _, alias, _, _ = create_valid_fixture_alias(conn)
    competition_id = rows(
        conn,
        """INSERT INTO competitions(competition_code,competition_name_cn,competition_type)
           VALUES ('alias-test','别名测试联赛','league') RETURNING id""",
    )[0][0]
    season_id = rows(
        conn,
        """INSERT INTO seasons(season_code,season_name)
           VALUES ('alias-test:2026','2026') RETURNING id""",
    )[0][0]
    competition_season_id = rows(
        conn,
        "INSERT INTO competition_seasons(competition_id,season_id) VALUES (%s,%s) RETURNING id",
        (competition_id, season_id),
    )[0][0]
    season_source_id = rows(
        conn,
        """INSERT INTO football_competition_season_sources
           (competition_season_id,source_name,id_system,source_competition_id,source_season_id,
            planned_start_date,planned_end_date,source_timezone,evidence)
           VALUES (%s,'sporttery','leagueId','72','alias-test:2026',
                   '2026-08-01','2027-05-31','Asia/Shanghai','{"source":"fixture"}')
           RETURNING id""",
        (competition_season_id,),
    )[0][0]
    conn.commit()

    with pytest.raises(RaiseException, match="aliased fixture cannot be changed"):
        rows(
            conn,
            """INSERT INTO football_fixture_seasons
               (fixture_id,season_source_id,source_name,match_id_system,source_match_id,evidence)
           VALUES (%s,%s,'sporttery','traditional.t14c.26001.matchOrder','1','{"source":"fixture"}')
               RETURNING fixture_id""",
            (alias, season_source_id),
        )
    conn.rollback()
    assert rows(
        conn, "SELECT count(*) FROM football_fixture_seasons WHERE fixture_id=%s", (alias,)
    ) == [(0,)]


def test_alias_creation_rejects_unknown_result_provenance(ready):
    conn = ready
    official(conn)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,'{}'),
                  ('sporttery','traditional.t14c.26001.matchOrder','1',%s,'{}'),
                  ('sporttery','traditional.r9.26001.matchOrder','1',%s,'{}')
           RETURNING source_match_id""",
        (canonical, alias, alias),
    )
    for game_type, source_result_source in (
        ("t14c", "sporttery_history_api"),
        ("r9", None),
    ):
        issue = store_pool_issue(conn, "26001", game_type, None, None, 14, "finished", {})
        rows(
            conn,
            """INSERT INTO football_pool_issue_matches
               (issue_id,match_order,league_name,home_team_name,away_team_name,
                source_result_source,fixture_id,identity_status,identity_evidence)
               VALUES (%s,1,'英超','主1','客1',%s,%s,'linked','{}') RETURNING id""",
            (issue, source_result_source, alias),
        )

    with pytest.raises(RaiseException, match="only linked traditional Sporttery"):
        rows(
            conn,
            """INSERT INTO football_fixture_identity_aliases
               (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
               VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
            (
                alias,
                canonical,
                Json(
                    {
                        "contract": "football-fixture-alias/v1",
                        "basis": "direct_sporttery_match_id",
                        "source_match_id": "9001",
                        "candidate_snapshot_sha256": "a" * 64,
                    }
                ),
            ),
        )
    conn.rollback()


def test_concurrent_alias_inserts_cannot_form_a_cycle(ready):
    conn = ready
    official(conn, source="9001", code="周五001")
    official(conn, source="9002", code="周五002")
    fixture_a = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    fixture_b = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','traditional.t14c.26001.matchOrder','1',%s,'{}'),
                  ('sporttery','traditional.r9.26001.matchOrder','1',%s,'{}')
           RETURNING source_match_id""",
        (fixture_a, fixture_b),
    )
    for game_type in ("t14c", "r9"):
        issue = store_pool_issue(conn, "26001", game_type, None, None, 14, "finished", {})
        rows(
            conn,
            """INSERT INTO football_pool_issue_matches
               (issue_id,match_order,league_name,home_team_name,away_team_name,
                source_result_source,fixture_id,identity_status,identity_evidence)
               VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
               RETURNING id""",
            (issue, fixture_a if game_type == "t14c" else fixture_b),
        )
    schema = rows(conn, "SELECT current_schema()")[0][0]
    conn.commit()

    def insert_alias(alias_fixture, canonical_fixture, source_id):
        try:
            with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as other:
                with other.cursor() as cur:
                    cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                    cur.execute("SET statement_timeout='10s'")
                    cur.execute("SET lock_timeout='5s'")
                    cur.execute(
                        """INSERT INTO football_fixture_source_links
                           (source_name,id_system,source_match_id,fixture_id,evidence)
                           VALUES ('sporttery','jc.matchId',%s,%s,'{}') RETURNING fixture_id""",
                        (source_id, canonical_fixture),
                    )
                evidence = Json(
                    {
                        "contract": "football-fixture-alias/v1",
                        "basis": "direct_sporttery_match_id",
                        "source_match_id": source_id,
                        "candidate_snapshot_sha256": "a" * 64,
                    }
                )
                with other.cursor() as cur:
                    cur.execute(
                        """INSERT INTO football_fixture_identity_aliases
                           (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
                           VALUES (%s,%s,%s,%s) RETURNING alias_fixture_id""",
                        (alias_fixture, canonical_fixture, source_id, evidence),
                    )
                other.commit()
                return "inserted"
        except Exception as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda args: insert_alias(*args),
                ((fixture_a, fixture_b, "9002"), (fixture_b, fixture_a, "9001")),
            )
        )
    assert outcomes.count("inserted") == 1
    assert sum("aliased fixture cannot be changed" in result for result in outcomes) == 1
    assert rows(conn, "SELECT count(*) FROM football_fixture_identity_aliases") == [(1,)]
    assert rows(
        conn,
        """SELECT a.alias_fixture_id,a.canonical_fixture_id
           FROM football_fixture_identity_aliases a""",
    ) in ([(fixture_a, fixture_b)], [(fixture_b, fixture_a)])


def test_alias_insert_serializes_with_a_concurrent_source_link_write(ready):
    conn = ready
    canonical, alias, _, _ = create_valid_fixture_alias(conn, insert_alias=False)
    schema = rows(conn, "SELECT current_schema()")[0][0]
    conn.commit()
    alias_inserted = Event()
    allow_alias_commit = Event()
    writer_started = Event()

    def insert_alias():
        with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as other:
            with other.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cur.execute("SET lock_timeout='5s'")
                cur.execute(
                    """INSERT INTO football_fixture_identity_aliases
                       (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
                       VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
                    (
                        alias,
                        canonical,
                        Json(
                            {
                                "contract": "football-fixture-alias/v1",
                                "basis": "direct_sporttery_match_id",
                                "source_match_id": "9001",
                                "candidate_snapshot_sha256": "a" * 64,
                            }
                        ),
                    ),
                )
            alias_inserted.set()
            if not allow_alias_commit.wait(timeout=5):
                raise TimeoutError("test did not release alias transaction")
            other.commit()
            return "inserted"

    def insert_source_link():
        if not alias_inserted.wait(timeout=5):
            return "alias transaction did not reach its trigger"
        with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as other:
            with other.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                cur.execute("SET lock_timeout='5s'")
                cur.execute("SELECT set_config('application_name','p132-alias-write',false)")
                writer_started.set()
                try:
                    cur.execute(
                        """INSERT INTO football_fixture_source_links
                           (source_name,id_system,source_match_id,fixture_id,evidence)
                           VALUES ('sporttery','other.matchId','race-5001',%s,'{}')
                           RETURNING fixture_id""",
                        (alias,),
                    )
                except Exception as error:
                    other.rollback()
                    return str(error)
            other.commit()
            return "inserted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        alias_future = executor.submit(insert_alias)
        assert alias_inserted.wait(timeout=5)
        writer_future = executor.submit(insert_source_link)
        assert writer_started.wait(timeout=5)
        deadline = monotonic() + 5
        observed_advisory_wait = False
        while monotonic() < deadline:
            activity = rows(
                conn,
                """SELECT wait_event_type,wait_event FROM pg_stat_activity
                   WHERE application_name='p132-alias-write'""",
            )
            if activity and activity[0] == ("Lock", "advisory"):
                observed_advisory_wait = True
                break
            sleep(0.02)
        allow_alias_commit.set()
        assert observed_advisory_wait
        assert alias_future.result(timeout=5) == "inserted"
        assert "aliased fixture cannot be changed" in writer_future.result(timeout=5)
    assert rows(conn, "SELECT count(*) FROM football_fixture_identity_aliases") == [(1,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_fixture_source_links WHERE fixture_id=%s",
        (alias,),
    ) == [(1,)]


def test_alias_migration_ddl_rolls_back_as_one_transaction(database):
    conn = database
    migrate(conn)
    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/08_season_team_database.sql").read_text())
        cur.execute((ROOT / "sql/127_football_fixture_seasons.sql").read_text())
        cur.execute(
            "CREATE TABLE local_schema_migrations(filename TEXT PRIMARY KEY, checksum_sha256 TEXT)"
        )
        cur.execute((ROOT / "sql/128_traditional_history_facts.sql").read_text())
    conn.commit()
    original_view = rows(
        conn,
        """SELECT column_name,data_type,ordinal_position
           FROM information_schema.columns
           WHERE table_schema=current_schema() AND table_name='football_pool_fixture_catalog'
           ORDER BY ordinal_position""",
    )

    with conn.cursor() as cur:
        cur.execute((ROOT / "sql/129_football_fixture_identity_aliases.sql").read_text())
        assert rows(conn, "SELECT to_regclass('football_fixture_identity_aliases')") == [
            ("football_fixture_identity_aliases",)
        ]
        assert rows(conn, "SELECT count(*) FROM football_fixture_identity_aliases") == [(0,)]
    conn.rollback()

    assert rows(conn, "SELECT to_regclass('football_fixture_identity_aliases')") == [(None,)]
    assert (
        rows(
            conn,
            """SELECT column_name,data_type,ordinal_position
           FROM information_schema.columns
           WHERE table_schema=current_schema() AND table_name='football_pool_fixture_catalog'
           ORDER BY ordinal_position""",
        )
        == original_view
    )


def test_fixture_alias_is_append_only_and_application_role_cannot_rewrite_it(ready):
    conn = ready
    mid = official(conn)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,'{}'),
                  ('sporttery','traditional.t14c.26001.matchOrder','1',%s,'{}')
           RETURNING source_match_id""",
        (canonical, alias),
    )
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 1, "finished", {})
    rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias),
    )
    schema = rows(conn, "SELECT current_schema()")[0][0]
    alias_table = sql.Identifier(schema, "football_fixture_identity_aliases")
    catalog_view = sql.Identifier(schema, "football_pool_fixture_catalog")
    with conn.cursor() as cur:
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL("GRANT SELECT ON {},{},{} TO fqp").format(
                sql.Identifier(schema, "official_matches"),
                sql.Identifier(schema, "football_pool_issue_matches"),
                sql.Identifier(schema, "football_pool_issues"),
            )
        )
        cur.execute("SET LOCAL ROLE fqp")
        cur.execute(
            sql.SQL("""INSERT INTO {}
                (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
                VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""").format(alias_table),
            (
                alias,
                canonical,
                Json(
                    {
                        "contract": "football-fixture-alias/v1",
                        "basis": "direct_sporttery_match_id",
                        "source_match_id": "9001",
                        "candidate_snapshot_sha256": "a" * 64,
                    }
                ),
            ),
        )
        assert cur.fetchone() == (alias,)
        cur.execute(
            sql.SQL("SELECT fixture_id,official_match_id FROM {} WHERE fixture_id=%s").format(
                catalog_view
            ),
            (canonical,),
        )
        assert cur.fetchone() == (canonical, mid)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    with pytest.raises(InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("UPDATE {} SET evidence='{{}}'::jsonb").format(alias_table))
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    with pytest.raises(InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}").format(alias_table))
    conn.rollback()
    with pytest.raises(RaiseException, match="immutable"):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}").format(alias_table))
    conn.rollback()


def test_fixture_linker_normalizes_aliases_and_checks_equivalent_fixture_revisions(ready):
    conn = ready
    official(conn)
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    alias = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,%s),
                  ('sporttery','traditional.t14c.26001.matchOrder','1',%s,%s)
           RETURNING source_match_id""",
        (
            canonical,
            Json({"home_team_name": "主1", "away_team_name": "客1"}),
            alias,
            Json({"home_team_name": "主1", "away_team_name": "客1"}),
        ),
    )
    issue = store_pool_issue(conn, "26001", "t14c", None, None, 1, "finished", {})
    rows(
        conn,
        """INSERT INTO football_pool_issue_matches
           (issue_id,match_order,league_name,home_team_name,away_team_name,
            source_result_source,fixture_id,identity_status,identity_evidence)
           VALUES (%s,1,'英超','主1','客1','sporttery_history_api',%s,'linked','{}')
           RETURNING id""",
        (issue, alias),
    )
    rows(
        conn,
        """INSERT INTO football_fixture_identity_aliases
           (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
           VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
        (
            alias,
            canonical,
            Json(
                {
                    "contract": "football-fixture-alias/v1",
                    "basis": "direct_sporttery_match_id",
                    "source_match_id": "9001",
                    "candidate_snapshot_sha256": "a" * 64,
                }
            ),
        ),
    )

    from scripts.football_fixture_identity import _bind_fixture

    with conn.cursor() as cur:
        compatible = _bind_fixture(
            cur,
            [("sporttery", "traditional.t14c.26001.matchOrder", "1")],
            {"league_name": "英超", "home_team_name": "主1", "away_team_name": "客1"},
            {alias, canonical},
            {"league_name": "英超", "home_team_name": "主1", "away_team_name": "客1"},
            None,
        )
    assert compatible["identity_status"] == "linked"
    assert compatible["fixture_id"] == canonical

    rows(
        conn,
        """INSERT INTO football_pool_fixture_revisions
           (issue_id,match_order,fixture_id,content_sha256,material_json)
           VALUES (%s,1,%s,repeat('b',64),
                   '{"league_name":"英超","home_team_name":"冲突队","away_team_name":"客1"}')
           RETURNING id""",
        (issue, alias),
    )
    with conn.cursor() as cur:
        conflicted = _bind_fixture(
            cur,
            [("sporttery", "traditional.t14c.26001.matchOrder", "1")],
            {"league_name": "英超", "home_team_name": "主1", "away_team_name": "客1"},
            {canonical},
            {"league_name": "英超", "home_team_name": "主1", "away_team_name": "客1"},
            None,
        )
    assert conflicted["identity_status"] == "conflict"


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


def test_explicit_traditional_slot_group_links_completed_products_without_jc_alias(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    for game_type, order in (("bqc6", 5), ("r9", 6), ("t14c", 6)):
        put_traditional_history_slot(
            conn,
            game_type,
            "22036",
            order,
            source_match_id="1010262" if game_type == "bqc6" else None,
        )
    slots = [
        {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
        {"game_type": "r9", "issue_no": "22036", "match_order": 6},
        {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
    ]

    linked = link_traditional_issue_slot_group(conn, slots)

    assert linked["identity_status"] == "linked"
    assert linked["inserted_fixture"] is True
    assert linked["inserted_source_links"] == 3
    assert linked["updated_memberships"] == 3
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id),min(identity_status),min(match_id) "
        "FROM football_pool_issue_matches",
    ) == [(3, 1, "linked", None)]
    assert rows(
        conn,
        "SELECT id_system,source_match_id,fixture_id FROM football_fixture_source_links "
        "ORDER BY id_system",
    ) == [
        ("traditional.bqc6.22036.matchOrder", "5", linked["fixture_id"]),
        ("traditional.r9.22036.matchOrder", "6", linked["fixture_id"]),
        ("traditional.t14c.22036.matchOrder", "6", linked["fixture_id"]),
    ]
    assert rows(
        conn,
        "SELECT count(*) FROM football_fixture_source_links WHERE id_system='jc.matchId'",
    ) == [(0,)]
    assert rows(
        conn,
        "SELECT source_match_id FROM football_pool_issue_matches WHERE source_match_id IS NOT NULL",
    ) == [("1010262",)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(6,)]
    repeated = link_traditional_issue_slot_group(conn, slots)
    assert repeated["fixture_id"] == linked["fixture_id"]
    assert repeated["inserted_fixture"] is False
    assert repeated["inserted_source_links"] == 0
    assert repeated["updated_memberships"] == 0
    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(1,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(3,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(6,)]


def test_explicit_traditional_slot_group_replay_normalizes_an_existing_alias(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    slots = [
        {"game_type": "r9", "issue_no": "22036", "match_order": 6},
        {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
    ]
    for slot in slots:
        put_traditional_history_slot(conn, **slot)
    initial = link_traditional_issue_slot_group(conn, slots)
    alias = initial["fixture_id"]
    official(conn, source="9001")
    canonical = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','jc.matchId','9001',%s,'{}') RETURNING fixture_id""",
        (canonical,),
    )
    rows(
        conn,
        """INSERT INTO football_fixture_identity_aliases
           (alias_fixture_id,canonical_fixture_id,source_match_id,evidence)
           VALUES (%s,%s,'9001',%s) RETURNING alias_fixture_id""",
        (
            alias,
            canonical,
            Json(
                {
                    "contract": "football-fixture-alias/v1",
                    "basis": "direct_sporttery_match_id",
                    "source_match_id": "9001",
                    "candidate_snapshot_sha256": "a" * 64,
                }
            ),
        ),
    )
    conn.commit()

    replay = link_traditional_issue_slot_group(conn, slots)

    assert replay["identity_status"] == "linked"
    assert replay["fixture_id"] == canonical
    assert replay["inserted_fixture"] is False
    assert replay["inserted_source_links"] == 0
    assert replay["updated_memberships"] == 0
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id) FROM football_pool_issue_matches",
    ) == [(2, 1)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches WHERE fixture_id=%s",
        (alias,),
    ) == [(2,)]


def test_explicit_traditional_slot_group_accepts_p128_fill_evidence_shape(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    for game_type, order in (("bqc6", 5), ("r9", 6)):
        put_traditional_history_slot(conn, game_type, "22036", order)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,source_raw_json,kickoff_evidence,source_result_evidence "
            "FROM football_pool_issue_matches ORDER BY match_order"
        )
        members = cur.fetchall()
        cur.execute(
            "SELECT i.id,i.raw_json FROM football_pool_issues i "
            "JOIN football_pool_issue_matches m ON m.issue_id=i.id "
            "ORDER BY m.match_order"
        )
        issues = cur.fetchall()
        for membership_id, source_raw, kickoff, result in members:
            receipt = source_raw.pop("import_receipt")
            cur.execute(
                "UPDATE football_pool_issue_matches SET source_raw_json=%s,"
                "kickoff_evidence=%s,source_result_evidence=%s WHERE id=%s",
                (
                    Json(
                        {
                            "legacy_member": {"retained": True},
                            "sporttery_history_import": {
                                "receipt": receipt,
                                "source": source_raw,
                            },
                        }
                    ),
                    Json(
                        {
                            "sporttery_history_import": {
                                "receipt": receipt,
                                "evidence": kickoff,
                            }
                        }
                    ),
                    Json(
                        {
                            "sporttery_history_import": {
                                "receipt": receipt,
                                "evidence": result,
                            }
                        }
                    ),
                    membership_id,
                ),
            )
        for issue_id, raw in issues:
            receipt = raw.pop("import_receipt")
            cur.execute(
                "UPDATE football_pool_issues SET raw_json=%s WHERE id=%s",
                (
                    Json(
                        {
                            "legacy_header": raw,
                            "traditional_history_import": {
                                "receipt": receipt,
                                "evidence": {"source": "sporttery_history_api"},
                                "header_state_sha256": "d" * 64,
                            },
                        }
                    ),
                    issue_id,
                ),
            )

    linked = link_traditional_issue_slot_group(
        conn,
        [
            {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
            {"game_type": "r9", "issue_no": "22036", "match_order": 6},
        ],
    )

    assert linked["identity_status"] == "linked"
    assert linked["updated_memberships"] == 2
    assert all(
        slot["source_import_receipt"]["contract"] == "sporttery-traditional-history-import/v1"
        for slot in linked["evidence"]["slots"]
    )


def _p129_500com_half_score_supplement():
    return {
        "source": "500.com_wanchang_exact_fixture_reconciliation",
        "contract": "sporttery-half-score-secondary-supplement/v1",
        "source_file": "https://live.500.com/wanchang.php?e=2022-04-06",
        "source_table": "wanchang.php historical finished-score row",
        "api_result_code": "3",
        "identity_checks": {
            "event_date_and_official_full_score_exact": True,
            "finished_source_record_has_valid_half_score": True,
            "official_away_team_exact_or_same_unique_titan_id": True,
            "official_home_team_exact_or_same_unique_titan_id": True,
            "only_one_source_fixture_matches_date_direction_and_full_score": True,
        },
        "manifest_sha256": "b637cdd2943e1e5a1ba10844af7a0d2ed9bba8f154f735a9b476f63d48a6ada8",
        "source_match_id": 984924,
        "source_updated_at": "2026-11-02T11:20:51+08:00",
        "sporttery_match_id": None,
        "source_titan_match_id": None,
        "secondary_source_records": [
            {
                "league": "英超",
                "source": "500.com",
                "away_team": "埃弗顿",
                "home_team": "伯恩利",
                "event_date": "2022-04-07",
                "full_score": [3, 2],
                "half_score": [1, 2],
                "source_url": "https://live.500.com/wanchang.php?e=2022-04-06",
                "page_sha256": "64d5ee7ba3b807d37abdc40c76ab0ffe7b7d13dacd4218160b3ade44e9ab5d95",
                "kickoff_time": "02:30",
                "away_identity": {
                    "method": "same_unique_titan_team_id",
                    "source_name": "埃弗顿",
                    "official_name": "埃弗顿",
                    "source_titan_team_ids": [31],
                    "official_titan_team_ids": [31],
                },
                "home_identity": {
                    "method": "same_unique_titan_team_id",
                    "source_name": "伯恩利",
                    "official_name": "伯恩利",
                    "source_titan_team_ids": [46],
                    "official_titan_team_ids": [46],
                },
                "source_match_id": 984924,
                "requested_page_date": "2022-04-06",
                "titan_match_ids_cross_checked": [],
                "titan_half_scores_cross_checked": [],
            }
        ],
        "api_full_score_source_text": "3:2",
        "api_half_score_source_text": "{}",
        "secondary_half_score_source_text": "1:2",
        "production_evidence_half_score_source_text": "{}",
    }


def _seed_p131_openligadb_identity_group(
    conn, *, mutate_supplement=None, evidence_key=None, omit_optional=False
):
    from copy import deepcopy

    sample = json.loads(
        (ROOT / "scripts/data/traditional_half_score_supplement_allowlist.json").read_text()
    )["verification_example"]
    supplement = deepcopy(sample["supplement"])
    if omit_optional:
        supplement.pop("production_evidence_half_score_source_text", None)
        supplement.pop("secondary_source_records", None)
    if mutate_supplement:
        mutate_supplement(supplement)
    products = [
        ("jq4", "21109", 1, "{}"),
        ("r9", "21109", 7, "4:0"),
        ("t14c", "21109", 7, "4:0"),
    ]
    for game_type, issue_no, match_order, source_half in products:
        put_traditional_history_slot(
            conn,
            game_type,
            issue_no,
            match_order,
            full=(7, 0),
            half=(4, 0),
            result_code="3＋,0",
            league_name="德甲",
            home_team_name="拜仁慕尼黑",
            away_team_name="波鸿",
            kickoff_date="2021-09-18",
            half_score_source_text=source_half,
        )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,source_raw_json FROM football_pool_issue_matches "
            "WHERE issue_id=(SELECT id FROM football_pool_issues "
            "WHERE game_type='jq4' AND issue_no='21109') AND match_order=1"
        )
        membership_id, source_raw = cur.fetchone()
        primary = {
            "source": "sporttery_history_api",
            "issue_no": "21109",
            "game_no": 94,
            "match_num": 1,
            "full_score_source_text": "7:0",
            "half_score_source_text": "{}",
            "product_result_code_source_text": "3＋,0",
        }
        result_evidence = {
            "sporttery_history_import": {
                "receipt": source_raw["import_receipt"],
                "evidence": primary,
            },
            evidence_key or sample["evidence_key"]: supplement,
        }
        cur.execute(
            "UPDATE football_pool_issue_matches SET source_result_evidence=%s WHERE id=%s",
            (Json(result_evidence), membership_id),
        )
    return [
        {"game_type": game_type, "issue_no": issue_no, "match_order": match_order}
        for game_type, issue_no, match_order, _ in products
    ]


def test_p131_static_allowlist_is_pinned_and_has_unique_slots(monkeypatch):
    import scripts.football_fixture_identity as identity

    entries = identity._traditional_half_score_supplement_allowlist()
    assert len(entries) == 4557
    assert len(entries) == len(set(entries))

    identity._traditional_half_score_supplement_allowlist.cache_clear()
    monkeypatch.setattr(identity, "TRADITIONAL_HALF_SCORE_SUPPLEMENT_ALLOWLIST_SHA256", "0" * 64)
    assert identity._traditional_half_score_supplement_allowlist() == {}
    identity._traditional_half_score_supplement_allowlist.cache_clear()


def test_explicit_traditional_slot_group_accepts_pinned_p131_openligadb_receipt(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    slots = _seed_p131_openligadb_identity_group(conn)

    linked = link_traditional_issue_slot_group(conn, slots)

    assert linked["identity_status"] == "linked"
    assert linked["updated_memberships"] == 3
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id),min(identity_status) "
        "FROM football_pool_issue_matches",
    ) == [(3, 1, "linked")]
    assert rows(
        conn,
        "SELECT count(*) FROM football_fixture_source_links WHERE id_system='jc.matchId'",
    ) == [(0,)]


def test_explicit_traditional_slot_group_accepts_legacy_p131_receipt_without_optional_fields(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    slots = _seed_p131_openligadb_identity_group(conn, omit_optional=True)

    linked = link_traditional_issue_slot_group(conn, slots)

    assert linked["identity_status"] == "linked"
    assert linked["updated_memberships"] == 3
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id),min(identity_status) "
        "FROM football_pool_issue_matches",
    ) == [(3, 1, "linked")]


def test_explicit_traditional_slot_group_rejects_p131_receipt_reused_for_another_event(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    slots = _seed_p131_openligadb_identity_group(conn)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE football_pool_issue_matches SET home_team_name='伪造球队',"
            "source_raw_json=jsonb_set(source_raw_json,'{home_team_name}','\"伪造球队\"') "
            "WHERE issue_id=(SELECT id FROM football_pool_issues "
            "WHERE game_type='jq4' AND issue_no='21109') AND match_order=1"
        )

    with pytest.raises(ValueError, match="traditional_slot_source_evidence_mismatch"):
        link_traditional_issue_slot_group(conn, slots)

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]


@pytest.mark.parametrize(
    "tamper,evidence_key",
    [
        ("core", None),
        ("source_record", None),
        ("manifest_type", None),
        (None, "unreviewed_supplement_key"),
    ],
    ids=[
        "core-receipt-tampered",
        "known-key-is-not-enough",
        "invalid-manifest-type",
        "unknown-evidence-key",
    ],
)
def test_explicit_traditional_slot_group_rejects_unpinned_p131_receipt(ready, tamper, evidence_key):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready

    def mutate(receipt):
        if tamper == "core":
            receipt["source_match_id"] = 999999
        elif tamper == "source_record":
            receipt["secondary_source_records"][0]["source_match_id"] = 999999
        elif tamper == "manifest_type":
            receipt["manifest_sha256"] = ["not", "hashable"]

    slots = _seed_p131_openligadb_identity_group(
        conn,
        mutate_supplement=mutate if tamper is not None else None,
        evidence_key=evidence_key,
    )

    with pytest.raises(ValueError, match="traditional_slot_source_evidence_mismatch"):
        link_traditional_issue_slot_group(conn, slots)

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]


def _attach_p129_500com_half_score_supplement(
    conn,
    game_type,
    order,
    *,
    mutate=None,
    mutate_primary=None,
    fill_result_shape=False,
    source_numeric_strings=True,
):
    from psycopg2.extras import Json

    issue_id = put_traditional_history_slot(conn, game_type, "22036", order, half=(1, 2))
    supplement = _p129_500com_half_score_supplement()
    if mutate:
        mutate(supplement)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id,source_raw_json FROM football_pool_issue_matches "
            "WHERE issue_id=%s AND match_order=%s",
            (issue_id, order),
        )
        membership_id, source_raw = cur.fetchone()
        source_raw["half_score_source_text"] = "{}"
        primary_evidence = {
            "source": "sporttery_history_api",
            "issue_no": "22036",
            "game_no": "90" if source_numeric_strings else 90,
            "match_num": str(order) if source_numeric_strings else order,
            "full_score_source_text": "3:2",
            "half_score_source_text": "{}",
            "product_result_code_source_text": "3",
        }
        if mutate_primary:
            mutate_primary(primary_evidence)
        if fill_result_shape:
            result_evidence = {
                "sporttery_history_import": {
                    "receipt": source_raw["import_receipt"],
                    "evidence": primary_evidence,
                }
            }
        else:
            result_evidence = primary_evidence
        result_evidence["fivehundredcom_half_score_supplement_20261102"] = supplement
        cur.execute(
            "UPDATE football_pool_issue_matches SET source_raw_json=%s,source_result_evidence=%s "
            "WHERE id=%s",
            (
                Json(source_raw),
                Json(result_evidence),
                membership_id,
            ),
        )


@pytest.mark.parametrize("fill_result_shape", [False, True], ids=["new_import", "fill_import"])
@pytest.mark.parametrize(
    "source_numeric_strings", [False, True], ids=["json_integers", "source_strings"]
)
def test_explicit_traditional_slot_group_accepts_pinned_500com_half_score_evidence(
    ready, fill_result_shape, source_numeric_strings
):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    _attach_p129_500com_half_score_supplement(
        conn,
        "r9",
        6,
        fill_result_shape=fill_result_shape,
        source_numeric_strings=source_numeric_strings,
    )
    _attach_p129_500com_half_score_supplement(
        conn,
        "t14c",
        6,
        fill_result_shape=fill_result_shape,
        source_numeric_strings=source_numeric_strings,
    )

    linked = link_traditional_issue_slot_group(
        conn,
        [
            {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
            {"game_type": "r9", "issue_no": "22036", "match_order": 6},
            {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
        ],
    )

    assert linked["identity_status"] == "linked"
    assert linked["updated_memberships"] == 3
    assert rows(
        conn,
        "SELECT count(*),count(DISTINCT fixture_id),min(identity_status) "
        "FROM football_pool_issue_matches",
    ) == [(3, 1, "linked")]
    assert rows(
        conn,
        "SELECT count(*) FROM football_fixture_source_links WHERE id_system='jc.matchId'",
    ) == [(0,)]


def _tamper_p129_source_match_id(supplement):
    supplement["source_match_id"] = 984925
    supplement["secondary_source_records"][0]["source_match_id"] = 984925


def _tamper_p129_page_hash(supplement):
    supplement["secondary_source_records"][0]["page_sha256"] = "f" * 64


def _tamper_p129_team_ids(supplement):
    identity = supplement["secondary_source_records"][0]["home_identity"]
    identity["source_titan_team_ids"] = [999]
    identity["official_titan_team_ids"] = [999]


@pytest.mark.parametrize("fill_result_shape", [False, True], ids=["new_import", "fill_import"])
@pytest.mark.parametrize(
    "mutate",
    [
        lambda supplement: supplement.update(manifest_sha256="0" * 64),
        lambda supplement: supplement["identity_checks"].update(
            only_one_source_fixture_matches_date_direction_and_full_score=False
        ),
        lambda supplement: supplement["secondary_source_records"][0].update(
            home_team="A different team"
        ),
        _tamper_p129_source_match_id,
        _tamper_p129_page_hash,
        _tamper_p129_team_ids,
    ],
    ids=[
        "unapproved_manifest",
        "ambiguous_source",
        "team_mismatch",
        "source_match_id_with_pinned_manifest_claim",
        "page_hash_with_pinned_manifest_claim",
        "team_ids_with_pinned_manifest_claim",
    ],
)
def test_explicit_traditional_slot_group_rejects_tampered_500com_half_score_evidence(
    ready, mutate, fill_result_shape
):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    _attach_p129_500com_half_score_supplement(
        conn, "r9", 6, mutate=mutate, fill_result_shape=fill_result_shape
    )
    _attach_p129_500com_half_score_supplement(conn, "t14c", 6)

    with pytest.raises(ValueError, match="traditional_slot_source_evidence_mismatch"):
        link_traditional_issue_slot_group(
            conn,
            [
                {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
                {"game_type": "r9", "issue_no": "22036", "match_order": 6},
                {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
            ],
        )

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]


@pytest.mark.parametrize("fill_result_shape", [False, True], ids=["new_import", "fill_import"])
@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("game_no", True),
        ("game_no", "90x"),
        ("match_num", 6.0),
        ("match_num", "06"),
    ],
    ids=["boolean_game_no", "nondigit_game_no", "float_match_num", "leading_zero_match_num"],
)
def test_explicit_traditional_slot_group_rejects_noncanonical_primary_numbers(
    ready, fill_result_shape, field, bad_value
):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    _attach_p129_500com_half_score_supplement(
        conn,
        "r9",
        6,
        fill_result_shape=fill_result_shape,
        mutate_primary=lambda evidence: evidence.update({field: bad_value}),
    )
    _attach_p129_500com_half_score_supplement(conn, "t14c", 6, fill_result_shape=fill_result_shape)

    with pytest.raises(ValueError, match="traditional_slot_source_evidence_mismatch"):
        link_traditional_issue_slot_group(
            conn,
            [
                {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
                {"game_type": "r9", "issue_no": "22036", "match_order": 6},
                {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
            ],
        )

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]


def test_explicit_traditional_slot_group_rollback_leaves_pending_rows_and_no_fixture(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    for game_type, order in (("bqc6", 5), ("r9", 6), ("t14c", 6)):
        put_traditional_history_slot(conn, game_type, "22036", order)
    conn.commit()
    slots = [
        {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
        {"game_type": "r9", "issue_no": "22036", "match_order": 6},
        {"game_type": "t14c", "issue_no": "22036", "match_order": 6},
    ]

    link_traditional_issue_slot_group(conn, slots)
    conn.rollback()

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(3,)]


def test_explicit_traditional_slot_group_database_failure_rolls_back_partial_writes(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    put_traditional_history_slot(conn, "r9", "22036", 6)
    conn.commit()
    with conn.cursor() as cur:
        cur.execute(
            "ALTER TABLE football_pool_issue_matches ADD CONSTRAINT test_reject_slot_link "
            "CHECK (identity_status<>'linked' OR match_order<>5)"
        )
    conn.commit()

    with pytest.raises(CheckViolation):
        link_traditional_issue_slot_group(
            conn,
            [
                {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
                {"game_type": "r9", "issue_no": "22036", "match_order": 6},
            ],
        )

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_pool_fixture_revisions") == [(2,)]


def test_explicit_traditional_slot_group_rejects_unverified_existing_source_key(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    put_traditional_history_slot(conn, "r9", "22036", 6)
    first_fixture = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        """INSERT INTO football_fixture_source_links
           (source_name,id_system,source_match_id,fixture_id,evidence)
           VALUES ('sporttery','traditional.bqc6.22036.matchOrder','5',%s,'{}')
           RETURNING fixture_id""",
        (first_fixture,),
    )
    before_links = rows(
        conn,
        "SELECT source_name,id_system,source_match_id,fixture_id,evidence FROM football_fixture_source_links",
    )
    before_members = rows(
        conn,
        "SELECT id,identity_status,fixture_id FROM football_pool_issue_matches ORDER BY id",
    )

    with pytest.raises(ValueError, match="source_event_signature_conflict"):
        link_traditional_issue_slot_group(
            conn,
            [
                {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
                {"game_type": "r9", "issue_no": "22036", "match_order": 6},
            ],
        )

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(1,)]
    assert (
        rows(
            conn,
            "SELECT source_name,id_system,source_match_id,fixture_id,evidence FROM football_fixture_source_links",
        )
        == before_links
    )
    assert (
        rows(
            conn,
            "SELECT id,identity_status,fixture_id FROM football_pool_issue_matches ORDER BY id",
        )
        == before_members
    )


def test_explicit_traditional_slot_group_rejects_source_raw_fact_mismatch(ready):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    put_traditional_history_slot(conn, "r9", "22036", 6)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE football_pool_issue_matches SET source_raw_json="
            "jsonb_set(source_raw_json,'{home_team_name}','\"伪造球队\"') WHERE match_order=5"
        )

    with pytest.raises(ValueError, match="traditional_slot_source_evidence_mismatch"):
        link_traditional_issue_slot_group(
            conn,
            [
                {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
                {"game_type": "r9", "issue_no": "22036", "match_order": 6},
            ],
        )

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]


@pytest.mark.parametrize(
    "changes,reason",
    [
        ({"full": None, "half": None, "result_code": "*"}, "cancelled_or_unplayed_slot"),
        ({"full": (2, 2)}, "traditional_slots_do_not_match_exact_event_facts"),
    ],
)
def test_explicit_traditional_slot_group_rejects_cancelled_or_mismatched_rows(
    ready, changes, reason
):
    from scripts.football_fixture_identity import link_traditional_issue_slot_group

    conn = ready
    put_traditional_history_slot(conn, "bqc6", "22036", 5)
    put_traditional_history_slot(conn, "r9", "22036", 6, **changes)
    slots = [
        {"game_type": "bqc6", "issue_no": "22036", "match_order": 5},
        {"game_type": "r9", "issue_no": "22036", "match_order": 6},
    ]

    with pytest.raises(ValueError, match=reason):
        link_traditional_issue_slot_group(conn, slots)

    assert rows(conn, "SELECT count(*) FROM football_fixtures") == [(0,)]
    assert rows(conn, "SELECT count(*) FROM football_fixture_source_links") == [(0,)]
    assert rows(
        conn,
        "SELECT count(*) FROM football_pool_issue_matches "
        "WHERE fixture_id IS NOT NULL OR identity_status<>'pending'",
    ) == [(0,)]


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
        with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as other:
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
    with closing(psycopg2.connect(os.environ["FQP_HISTORY_TEST_DSN"])) as locker:
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


@pytest.fixture
def verified_league(history_ready):
    from scripts.football_fixture_identity import link_official_history_fixture

    conn = history_ready
    mid, bid = history_pair(conn)
    fid = link_official_history_fixture(conn, mid, batch_id=bid, source_match_id=5001)["fixture_id"]
    csid = history_season(conn, fid)["competition_season_id"]
    # Same clock/league and same-number foreign namespaces do not prove membership.
    extra = official(conn, source="9002", code="周五002")
    foreign = rows(conn, "INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")[0][0]
    rows(
        conn,
        "INSERT INTO football_fixture_source_links VALUES ('sporttery','uniformMatchId','9002',%s,'{}',now()) RETURNING fixture_id",
        (foreign,),
    )
    rows(
        conn,
        """INSERT INTO football_fixture_seasons(fixture_id,season_source_id,source_name,match_id_system,source_match_id,evidence)
        SELECT %s,season_source_id,'sporttery','uniformMatchId','9002',evidence FROM football_fixture_seasons
        WHERE fixture_id=%s RETURNING fixture_id""",
        (foreign, fid),
    )
    conn.commit()
    return conn, csid, mid, fid, extra


def test_verified_league_uses_explicit_members_outside_window_and_preserves_facts(verified_league):
    from scripts.league_reference_storage import league_catalog, league_fixtures, league_season

    conn, csid, mid, fid, _ = verified_league
    before = rows(conn, "SELECT to_jsonb(o) FROM official_matches o ORDER BY id")
    directory = league_catalog(conn, dataset="verified")
    assert directory["dataset"] == "verified"
    assert directory["competitions"][0]["seasons"] == [
        dict(id=csid, label="2024-2025", isCurrent=False)
    ]
    season = league_season(conn, csid, dataset="verified")
    assert season["coverage"] == dict(
        teams=None, expectedTeams=None, fixtures=1, expectedFixtures=None
    )
    assert season["overview"] is None and season["standings"] == {} and season["teams"] == []
    assert season["seasonIdentity"]["plannedEndDate"] == "2025-05-26"
    assert season["evidence"]["asOf"] is None and season["evidence"]["batchId"] is None
    result = league_fixtures(conn, csid, dataset="verified")
    assert result["total"] == 1 and len(result["rows"]) == 1
    row = result["rows"][0]
    assert row["id"] == f"fqp:fixture:{fid}"
    assert row["officialMatch"] == dict(id=mid, verification="verified")
    assert row["home"] == dict(id=None, name="主1", manager=None, stadium=None)
    assert row["status"] == "finished" and (row["homeGoals"], row["awayGoals"]) == (2, 1)
    assert datetime.fromisoformat(row["kickoff"]) == datetime.fromisoformat(
        "2026-10-30T20:00:00+08:00"
    )
    assert rows(conn, "SELECT to_jsonb(o) FROM official_matches o ORDER BY id") == before


@pytest.mark.parametrize(
    "query,total",
    [
        ({}, 1),
        ({"status": "finished"}, 1),
        ({"status": "upcoming"}, 0),
        ({"limit": 1, "offset": 1}, 1),
    ],
)
def test_verified_league_filters_and_exact_total(verified_league, query, total):
    from scripts.league_reference_storage import league_fixtures

    conn, csid, *_ = verified_league
    result = league_fixtures(conn, csid, dataset="verified", **query)
    assert result["total"] == total
    assert len(result["rows"]) == (0 if query.get("offset") or total == 0 else 1)


@pytest.mark.parametrize("match_status", ["scheduled", "finished", "postponed", "live", "unknown"])
def test_verified_league_pending_results_never_show_confirmed_score(verified_league, match_status):
    from scripts.league_reference_storage import league_fixtures

    conn, csid, mid, *_ = verified_league
    rows(
        conn,
        "UPDATE official_results SET result_status='pending' WHERE match_id=%s RETURNING id",
        (mid,),
    )
    rows(
        conn,
        "UPDATE official_matches SET match_status=%s WHERE id=%s RETURNING id",
        (match_status, mid),
    )
    result = league_fixtures(conn, csid, dataset="verified")
    assert result["rows"][0]["homeGoals"] is None
    assert result["rows"][0]["awayGoals"] is None
    assert result["rows"][0]["status"] == match_status


def test_verified_league_boundary_only_empty_season_is_not_inferred(verified_league):
    from scripts.football_season_identity import import_season
    from scripts.league_reference_storage import league_catalog, league_fixtures, league_season
    from tests.test_computation.test_football_season_identity import document, material

    conn, *_ = verified_league
    data = material()
    data.update(
        season_code="premier-league:2023-2024",
        season_name="2023-2024",
        boundary_document=document(season=10906),
        members=[],
        member_documents=[],
    )
    # Fixed evidence window is deliberately the same: dates never create a member.
    csid = import_season(conn, data)["competition_season_id"]
    conn.commit()
    directory = league_catalog(conn, dataset="verified")
    assert len(directory["competitions"][0]["seasons"]) == 2
    assert league_season(conn, csid, dataset="verified")["coverage"]["fixtures"] == 0
    assert league_fixtures(conn, csid, dataset="verified")["rows"] == []
    with pytest.raises(LookupError):
        league_season(conn, 999999, dataset="verified")


def test_verified_league_runs_as_restricted_readonly_and_serializes_via_api(
    verified_league, monkeypatch
):
    from contextlib import contextmanager

    from fastapi.testclient import TestClient

    from apps.backend.src.app import create_app
    from apps.backend.src.routers import league_data

    conn, csid, mid, *_ = verified_league
    with conn.cursor() as cur:
        cur.execute("SELECT current_schema()")
        schema = cur.fetchone()[0]
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {} TO fqp").format(sql.Identifier(schema))
        )
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SET ROLE fqp")
        cur.execute("SET TRANSACTION READ ONLY")

    @contextmanager
    def read_db():
        yield conn

    monkeypatch.setenv("FQP_AUTH_MODE", "none")
    monkeypatch.setattr(league_data, "get_db", read_db)
    client = TestClient(create_app())
    assert client.get("/api/league-data/catalog?dataset=verified").json()["dataset"] == "verified"
    detail = client.get(f"/api/league-data/seasons/{csid}?dataset=verified")
    assert detail.status_code == 200
    assert detail.json()["seasonIdentity"]["plannedEndDate"] == "2025-05-26"
    result = client.get(f"/api/league-data/seasons/{csid}/fixtures?dataset=verified&limit=1")
    assert result.status_code == 200 and result.json()["rows"][0]["officialMatch"]["id"] == mid
    assert rows(conn, "SHOW transaction_read_only") == [("on",)]
    assert rows(conn, "SHOW statement_timeout") == [("5s",)]
    assert rows(conn, "SHOW lock_timeout") == [("2s",)]
    assert rows(conn, "SELECT rolsuper FROM pg_roles WHERE rolname=current_user") == [(False,)]
    conn.rollback()


@pytest.mark.parametrize("key,value", [("batch_id", 1), ("team_id", 1), ("round_id", "r1")])
def test_verified_league_rejects_reference_filters(verified_league, key, value):
    from scripts.league_reference_storage import league_fixtures

    conn, csid, *_ = verified_league
    with pytest.raises(ValueError):
        league_fixtures(conn, csid, dataset="verified", **{key: value})
