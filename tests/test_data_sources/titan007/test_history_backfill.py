"""History import boundaries, including a disposable PostgreSQL publication."""

from __future__ import annotations

import csv
import gzip
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from scripts.sources.titan007.store import connect
from scripts.titan007_history import (
    DOMAINS,
    _official_match,
    export_package,
    import_package,
    normalize,
)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source.db"
    conn = connect(str(path))
    for mid in (1, 2, 3):
        conn.execute(
            "insert into matches(match_id,league_id,home_id,away_id,home_name,away_name,kickoff,status_code,home_score,away_score) values (?,36,10,20,'甲','乙','2024-01-01 20:00',?,2,1)",
            (mid, 0 if mid == 2 else -1),
        )
    # One source ID conflicts across the provider's two catalogs.
    conn.execute(
        "insert into league_results(match_id,league_id,home_id,away_id,match_time,status,home_score,away_score) values (3,36,10,20,'2024-01-01 20:00',-1,0,0)"
    )
    for mid in (1, 2, 3):
        conn.execute("insert into match_stats values (?,'控球率','55%','45%')", (mid,))
    conn.execute(
        "insert into lineups(match_id,side,player_name,player_id,starter) values (1,'home','球员',100,1)"
    )
    conn.execute("update lineups set player_name=?", ("球员,\n乙",))
    conn.execute(
        "insert into events(match_id,seq,minute,side,event_type,player_name) values (1,1,\"90+3'\",'home','入球','球员')"
    )
    conn.execute(
        "insert into odds_history(match_id,company_id,odds_type,source,seq,change_time,home,line,away) values (1,1,'europe','1x2d',1,'01-01 19:00',2,'3',4)"
    )
    conn.execute(
        "insert into player_appearances(match_id,player_id,side,starter,minutes) values (1,100,'home',1,90)"
    )
    conn.commit()
    conn.close()
    return path


def rows(package, name):
    with gzip.open(package / (name + ".csv.gz"), "rt", newline="") as f:
        return list(csv.reader(f))


def test_missing_acquisition_does_not_block_history_and_conflicts_are_excluded(source, tmp_path):
    package = tmp_path / "package"
    manifest = export_package(source, package, progress=lambda _: None)
    assert manifest["counts"]["matches"] == 2
    assert manifest["counts"]["match_stats"] == 1
    assert manifest["rejections"]["matches"] == {"score_conflict": 1}
    assert manifest["rejections"]["match_stats"] == {
        "not_finished": 1,
        "missing_or_conflicting_match": 1,
    }
    lineup = json.loads(rows(package, "lineups")[0][-1])
    assert lineup["source_acquired_at"] is None
    assert lineup["published_at"] is None
    assert lineup["roster_complete"] is False
    assert lineup["player_name"] == "球员,\n乙"
    stat = json.loads(rows(package, "match_stats")[0][-1])
    assert (stat["home_numeric"], stat["away_numeric"], stat["unit"]) == (55, 45, "percent")
    event = json.loads(rows(package, "events")[0][-1])
    assert (event["minute_base"], event["minute_added"]) == (90, 3)
    odds = json.loads(rows(package, "odds_history")[0][-1])
    assert odds["timeline_usable"] is False and odds["change_at"] is None
    appearance = rows(package, "player_appearances")[0]
    assert appearance[-2] == "derived" and json.loads(appearance[-1])["reported_minutes"] is False


def test_export_content_is_deterministic(source, tmp_path):
    a = export_package(source, tmp_path / "a", progress=lambda _: None)
    b = export_package(source, tmp_path / "b", progress=lambda _: None)
    assert a["content_sha256"] == b["content_sha256"]
    assert a["files"] == b["files"]


def test_overlapping_catalog_retains_verified_season(source, tmp_path):
    import sqlite3

    with sqlite3.connect(source) as conn:
        conn.execute(
            "insert into league_results(match_id,league_id,season,home_id,away_id,match_time,status,home_score,away_score) values (1,36,'2023-2024',10,20,'2024-01-01 20:00',-1,2,1)"
        )
    package = tmp_path / "package"
    export_package(source, package, progress=lambda _: None)
    match = rows(package, "matches")[0]
    assert match[0] == "1" and match[2] == "2023-2024"
    assert json.loads(match[12])["season_source_table"] == "league_results"


def test_conflicting_competition_cannot_supply_season(source, tmp_path):
    import sqlite3

    with sqlite3.connect(source) as conn:
        conn.execute(
            "insert into league_results(match_id,league_id,season,home_id,away_id,match_time,status,home_score,away_score) values (1,99,'2023-2024',10,20,'2024-01-01 20:00',-1,2,1)"
        )
    package = tmp_path / "package"
    manifest = export_package(source, package, progress=lambda _: None)
    assert manifest["rejections"]["matches"]["competition_conflict"] == 1
    assert "1" not in {r[0] for r in rows(package, "matches")}


def test_missing_score_uses_matching_complete_catalog_instead_of_rejecting(source, tmp_path):
    import sqlite3

    with sqlite3.connect(source) as conn:
        conn.execute("update matches set home_score=null,away_score=null where match_id=1")
        conn.execute(
            "insert into league_results(match_id,league_id,home_id,away_id,match_time,status,home_score,away_score) values (1,36,10,20,'2024-01-01 20:00',-1,2,1)"
        )
    package = tmp_path / "package"
    manifest = export_package(source, package, progress=lambda _: None)
    assert manifest["counts"]["match_stats"] == 1
    match = rows(package, "matches")[0]
    assert match[9:11] == ["2", "1"]
    assert json.loads(match[12])["score_gap_filled_from_league_results"] is True


def test_prediction_timestamp_is_not_publication_proof():
    side, origin, value = normalize(
        "predicted_lineups",
        {"side": "home", "announced_at": "2024-01-01T12:00:00", "player_name": "甲"},
        None,
    )
    assert origin == "prediction" and value["confirmed"] is False and value["published_at"] is None


def test_invalid_percentage_rejected():
    with pytest.raises(ValueError, match="invalid_percentage"):
        normalize(
            "match_stats",
            {"stat_key": "控球率", "home_value": "101%", "away_value": "0%"},
            {"match_status": "finished"},
        )


def test_official_link_requires_id_names_direction_and_kickoff():
    row = {
        "kickoff_at": "2024-01-01T12:00:00+00:00",
        "source_metadata": json.dumps(
            {
                "lottery_links": [
                    {
                        "lottery_match_id": 9,
                        "home_team": "甲",
                        "home_full_name": "甲队",
                        "away_team": "乙",
                        "away_full_name": "乙队",
                    }
                ]
            }
        ),
    }
    target = {
        "id": 90,
        "home_team_name": "甲队",
        "away_team_name": "乙队",
        "kickoff_time": "2024-01-01 20:00:00",
    }
    assert _official_match(row, {"9": target}) == 90
    assert _official_match(row, {"9": {**target, "kickoff_time": "2024-01-02 20:00:00"}}) is None
    assert _official_match(row, {"9": {**target, "home_team_name": "乙队"}}) is None


@pytest.fixture
def pg():
    dsn = os.environ.get("FQP_HISTORY_TEST_DSN")
    if not dsn:
        pytest.skip("isolated PostgreSQL DSN not supplied")
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extensions import parse_dsn

    params = parse_dsn(dsn)
    assert params["dbname"].startswith("fqp_history_test_") and params["host"] == "127.0.0.1"
    conn = psycopg2.connect(dsn)
    schema = "history_" + uuid4().hex
    with conn.cursor() as cur:
        cur.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        cur.execute(sql.SQL("set search_path to {},public").format(sql.Identifier(schema)))
        cur.execute("create table teams(id bigint primary key)")
        cur.execute("insert into teams values (10),(20)")
        cur.execute(
            "create table official_matches(id bigint primary key,source_match_id text,home_team_name text,away_team_name text,kickoff_time timestamp)"
        )
        cur.execute(
            "create table football_team_source_links(source_name text,id_system text,source_team_id text,team_id bigint)"
        )
        cur.execute(
            "insert into football_team_source_links values ('titan007','league_team','10',10),('titan007','league_team','20',20)"
        )
        migration = Path(__file__).resolve().parents[3] / "sql/119_football_history_backfill.sql"
        cur.execute(migration.read_text())
    conn.commit()
    try:
        yield conn
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("set search_path to public")
            cur.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def test_publication_dry_run_repeat_and_immutability(pg, source, tmp_path):
    import psycopg2

    package = tmp_path / "package"
    manifest = export_package(source, package, progress=lambda _: None)
    assert import_package(pg, package, dry_run=True, progress=lambda _: None)["status"] == "dry_run"
    with pg.cursor() as cur:
        cur.execute("select count(*) from football_history_batches")
        assert cur.fetchone()[0] == 0
    result = import_package(pg, package, progress=lambda _: None)
    pg.commit()
    assert result["status"] == "published"
    assert result["identity_coverage"]["home_links"] == 2
    assert import_package(pg, package, progress=lambda _: None)["status"] == "unchanged"
    with pg.cursor() as cur:
        cur.execute("select count(*) from football_history_available")
        assert cur.fetchone()[0] == sum(manifest["counts"][d] for d in DOMAINS)
        cur.execute(
            "select value_json->>'player_name' from football_history_available where domain='lineups'"
        )
        assert cur.fetchone()[0] == "球员,\n乙"
        cur.execute("savepoint immutable")
        with pytest.raises(psycopg2.Error):
            cur.execute("delete from football_history_records where domain='lineups'")
        cur.execute("rollback to savepoint immutable")
        with pytest.raises(psycopg2.Error):
            cur.execute("truncate football_history_records")
        cur.execute("rollback to savepoint immutable")
    pg.commit()


def test_corrupt_package_leaves_no_rows(pg, source, tmp_path):
    package = tmp_path / "package"
    export_package(source, package, progress=lambda _: None)
    with (package / "events.csv.gz").open("ab") as f:
        f.write(b"corrupt")
    with pytest.raises(ValueError, match="checksum mismatch"):
        import_package(pg, package, progress=lambda _: None)
    with pg.cursor() as cur:
        cur.execute("select count(*) from football_history_batches")
        assert cur.fetchone()[0] == 0


def test_copy_failure_rolls_back_whole_publication(pg, source, tmp_path):
    package = tmp_path / "package"
    manifest = export_package(source, package, progress=lambda _: None)
    manifest["counts"]["events"] += 1
    (package / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="record count mismatch"), pg:
        import_package(pg, package, progress=lambda _: None)
    with pg.cursor() as cur:
        for table in (
            "football_history_batches",
            "football_history_matches",
            "football_history_records",
        ):
            cur.execute("select count(*) from " + table)
            assert cur.fetchone()[0] == 0


def publish_odds_times(pg, kickoff, groups):
    """Publish untouched source strings, then query the separate time projection."""
    migration = Path(__file__).resolve().parents[3] / "sql/120_football_history_odds_timeline.sql"
    with pg.cursor() as cur:
        cur.execute(migration.read_text())
        cur.execute(
            migration.with_name("121_football_history_odds_parallel_safety.sql").read_text()
        )
        cur.execute(
            "insert into football_history_batches(source_name,content_sha256,normalization_version,manifest) "
            "values ('titan007',%s,'titan007-history/v1','{}') returning id",
            ("a" * 64,),
        )
        bid = cur.fetchone()[0]
        cur.execute(
            "insert into football_history_matches(batch_id,source_match_id,kickoff_at,match_status,"
            "source_home_team_id,source_away_team_id,source_metadata) "
            "values (%s,1,%s,'scheduled',10,20,'{}')",
            (bid, kickoff),
        )
        for company, source, items in groups:
            for i, (seq, raw) in enumerate(items):
                cur.execute(
                    "insert into football_history_records(batch_id,domain,source_record_key,"
                    "source_match_id,origin,value_json) values (%s,'odds_history',%s,1,'market',%s)",
                    (
                        bid,
                        f"{company}/{source}/{i}",
                        json.dumps(
                            {
                                "company_id": company,
                                "odds_type": "europe",
                                "source": source,
                                "seq": seq,
                                "change_time": raw,
                                "change_at": None,
                                "timeline_usable": False,
                                "home": 2.0,
                                "line": "3",
                                "away": 4.0,
                            }
                        ),
                    ),
                )
        cur.execute("update football_history_batches set state='published' where id=%s", (bid,))
    return bid


@pytest.mark.parametrize(
    ("kickoff", "raw", "expected", "reason"),
    [
        ("2024-01-28T12:00:00Z", "01-28 00:25", "2024-01-27T16:25:00+00:00", "unique_match_window"),
        ("2024-01-01T12:00:00Z", "12-31 23:59", "2023-12-31T15:59:00+00:00", "unique_match_window"),
        ("2023-12-31T15:30:00Z", "01-01 00:15", "2023-12-31T16:15:00+00:00", "unique_match_window"),
        ("2024-03-01T12:00:00Z", "02-29 19:00", "2024-02-29T11:00:00+00:00", "unique_match_window"),
        ("2023-03-01T12:00:00Z", "02-29 19:00", None, "outside_match_window"),
        ("2024-01-01T12:00:00Z", "01-01 24:00", None, "invalid_format"),
        ("2024-01-01T12:00:00Z", "02-30 12:00", None, "invalid_calendar_date"),
        ("2024-01-01T12:00:00Z", "01-03 12:00", None, "outside_match_window"),
        ("2024-01-01T12:00:00Z", "05-01 12:00", None, "outside_match_window"),
        ("2024-01-01T12:00:00Z", "", None, "missing_time"),
        ("2024-01-01T12:00:00Z", None, None, "missing_time"),
        (
            "2024-01-01T12:00:00Z",
            "2024-01-01T11:30:00Z",
            "2024-01-01T11:30:00+00:00",
            "source_full_time",
        ),
        (
            "2024-01-01T12:00:00Z",
            "2024-01-01 19:00",
            "2024-01-01T11:00:00+00:00",
            "source_full_time",
        ),
    ],
)
def test_odds_year_candidate_calendar_and_timezone(pg, kickoff, raw, expected, reason):
    from datetime import datetime

    publish_odds_times(pg, kickoff, [(1, "1x2d", [(1, raw)])])
    with pg.cursor() as cur:
        # The site's calendar, including its year, must not depend on the session zone.
        cur.execute("set local timezone='Pacific/Honolulu'")
        cur.execute(
            "select change_at,time_resolution_reason,timeline_usable,value_json->>'change_time',"
            "value_json->>'change_at',time_basis from football_history_odds_timeline"
        )
        at, why, usable, original, raw_at, basis = cur.fetchone()
    assert at == (datetime.fromisoformat(expected) if expected else None)
    assert why == reason and usable is (expected is not None)
    assert original == raw and raw_at is None
    assert basis == (
        "source_full"
        if reason == "source_full_time"
        else "inferred_year"
        if expected
        else "unresolved"
    )


@pytest.mark.parametrize(
    ("items", "direction", "usable"),
    [
        ([(1, "01-01 19:00"), (2, "12-31 23:00")], "descending", [True, True]),
        ([(1, "12-31 23:00"), (2, "01-01 19:00")], "ascending", [True, True]),
        ([(1, "01-01 19:00"), (2, "01-01 19:00")], "flat", [True, True]),
        ([(1, "01-01 19:00"), (2, "12-31 23:00"), (3, "01-01 18:00")], "conflict", [False] * 3),
        (
            [(1, "01-01 19:00"), (2, ""), (3, "12-31 23:00"), (4, "01-01 18:00")],
            "conflict",
            [False] * 4,
        ),
        ([(1, "01-01 19:00"), (2, ""), (3, "12-31 23:00")], "descending", [True, False, True]),
        ([(1, "01-01 19:00"), (1, "12-31 23:00")], "invalid_sequence", [False, False]),
        ([(None, "01-01 19:00")], "invalid_sequence", [False]),
    ],
)
def test_odds_year_group_sequence_including_gaps(pg, items, direction, usable):
    publish_odds_times(pg, "2024-01-01T12:00:00Z", [(1, "1x2d", items)])
    with pg.cursor() as cur:
        cur.execute(
            "select group_direction,timeline_usable,change_at from football_history_odds_timeline "
            "order by source_record_key"
        )
        rows = cur.fetchall()
    assert [r[0] for r in rows] == [direction] * len(items)
    assert [r[1] for r in rows] == usable
    assert all(r[2] is None for r in rows if not r[1])


def test_odds_year_groups_do_not_cross_companies_or_sources(pg):
    publish_odds_times(
        pg,
        "2024-01-01T12:00:00Z",
        [
            (1, "1x2d", [(1, "01-01 19:00"), (2, "12-31 23:00")]),
            (2, "1x2d", [(1, "12-31 23:00"), (2, "01-01 19:00")]),
            (1, "vip", [(1, "12-31 23:00"), (2, "01-01 19:00")]),
        ],
    )
    with pg.cursor() as cur:
        cur.execute("select count(*) from football_history_odds_timeline where timeline_usable")
        assert cur.fetchone()[0] == 6
        cur.execute("select has_table_privilege('fqp','football_history_odds_timeline','SELECT')")
        assert cur.fetchone()[0]


def test_odds_date_validation_disables_parallel_execution(pg):
    publish_odds_times(pg, "2024-01-01T12:00:00Z", [(1, "1x2d", [(1, "12-31 23:00")])])
    with pg.cursor() as cur:
        cur.execute(
            "select proparallel from pg_proc where oid="
            "'football_history_odds_time_candidate(text,timestamptz)'::regprocedure"
        )
        # Exception blocks validate individual candidate dates using subtransactions.
        # Even the parallel leader cannot run those; RESTRICTED is insufficient.
        assert cur.fetchone()[0] == "u"
        cur.execute("set local min_parallel_table_scan_size=0")
        cur.execute("set local min_parallel_index_scan_size=0")
        cur.execute("set local parallel_setup_cost=0")
        cur.execute("set local parallel_tuple_cost=0")
        cur.execute("set local debug_parallel_query=on")
        cur.execute("explain (format json) select count(*) from football_history_odds_timeline")
        assert "Gather" not in json.dumps(cur.fetchone()[0])


@pytest.mark.parametrize(
    "year,raw,expected",
    [
        ("2023", "12-07 11:11", "2023-12-07 11:11"),
        ("2025", "12-06 06:18", "2025-12-06 06:18"),
        (None, "04-02 03:42", "04-02 03:42"),
        ("2023", "02-29 12:00", "2023-02-29 12:00"),
    ],
)
def test_collector_keeps_source_year_through_sqlite(year, raw, expected, tmp_path):
    from scripts.sources.titan007.odds import parse_1x2d
    from scripts.sources.titan007.store import save_odds_history

    company = "|".join(["82", "999", "Example"] + ["2"] * 19)
    snap = "2|3|4|" + raw + "|1|1|1" + ("|" + year if year else "")
    parsed = parse_1x2d(f'var game=Array("{company}"); var gameDetail=Array("999^{snap}");')
    assert parsed["history"][0]["change_time"] == expected
    db = connect(str(tmp_path / "odds.db"))
    save_odds_history(db, 1, 82, "europe", "1x2d", parsed["history"])
    stored = db.execute("select change_time from odds_history").fetchone()[0]
    assert stored == expected
    db.close()


def evidence_migration(pg):
    path = Path(__file__).resolve().parents[3] / "sql/122_football_history_odds_evidence.sql"
    with pg.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute(path.with_name("123_football_history_odds_invalid_timezone.sql").read_text())


def time_evidence(pg, bid, key, at, *, basis="source_full", kickoff=None):
    from psycopg2.extras import Json

    with pg.cursor() as cur:
        cur.execute(
            "select value_json from football_history_records where batch_id=%s and source_record_key=%s",
            (bid, key),
        )
        value = cur.fetchone()[0]
        expected = {
            k: value[k]
            for k in (
                "company_id",
                "odds_type",
                "source",
                "seq",
                "change_time",
                "home",
                "line",
                "away",
            )
        }
        cur.execute(
            "select kickoff_at from football_history_matches where batch_id=%s and source_match_id=1",
            (bid,),
        )
        original = cur.fetchone()[0]
        provenance = {
            "home_team_id": 10,
            "away_team_id": 20,
            "official_url": "https://example.org/fixture",
            "source_year": at[:4],
            "event_url": "https://www.fifa.com/",
            "event_start": "2022-04-01T00:00:00+08:00",
            "anchor_at": "2022-11-20T10:00:00Z",
        }
        cur.execute(
            "insert into football_history_odds_time_evidence(batch_id,source_record_key,source_match_id,expected_value,change_at,time_basis,effective_kickoff_at,kickoff_basis,source_url,response_sha256,observed_at,provenance) values (%s,%s,1,%s,%s,%s,%s,%s,'https://1x2d.titan007.com/1.js',%s,now(),%s)",
            (
                bid,
                key,
                Json(expected),
                at,
                basis,
                kickoff or original,
                "source_and_official" if kickoff else "source_schedule",
                "b" * 64,
                Json(provenance),
            ),
        )


def test_verified_early_years_and_event_inference_leave_raw_history_unchanged(pg):
    from datetime import datetime

    bid = publish_odds_times(
        pg, "2022-11-22T10:00:00Z", [(1, "1x2d", [(1, "11-20 18:00"), (2, "04-02 03:42")])]
    )
    evidence_migration(pg)
    time_evidence(pg, bid, "1/1x2d/1", "2022-04-01T19:42:00Z", basis="inferred_year")
    with pg.cursor() as cur:
        cur.execute(
            "select change_at,time_basis,time_resolution_reason,timeline_usable,value_json->>'change_at' from football_history_odds_timeline where source_record_key='1/1x2d/1'"
        )
        at, basis, why, usable, raw = cur.fetchone()
        assert at == datetime.fromisoformat("2022-04-01T19:42:00+00:00")
        assert (basis, why, usable, raw) == ("inferred_year", "event_sequence_evidence", True, None)


def test_postponed_reference_kickoff_propagates_without_changing_source(pg):
    bid = publish_odds_times(
        pg, "2026-08-16T19:30:00Z", [(1, "1x2d", [(1, "10-20 03:16"), (2, "10-20 03:00")])]
    )
    evidence_migration(pg)
    time_evidence(pg, bid, "1/1x2d/0", "2026-10-19T19:16:00Z", kickoff="2026-10-19T19:15:00Z")
    with pg.cursor() as cur:
        cur.execute(
            "select time_basis,timeline_usable,kickoff_at,effective_kickoff_at,group_direction from football_history_odds_timeline order by source_record_key"
        )
        rows = cur.fetchall()
        assert [x[0] for x in rows] == ["source_full", "inferred_year"]
        assert all(x[1] and x[2] != x[3] and x[4] == "descending" for x in rows)
        cur.execute(
            "select has_table_privilege('fqp','football_history_odds_time_evidence','INSERT')"
        )
        assert not cur.fetchone()[0]


def test_full_source_dates_are_not_rejected_by_missing_year_window(pg):
    bid = publish_odds_times(pg, "2024-06-17T19:00:00Z", [(1, "1x2d", [(1, "2023-12-07 11:11")])])
    evidence_migration(pg)
    with pg.cursor() as cur:
        cur.execute(
            "select time_basis,timeline_usable,time_resolution_reason from football_history_odds_timeline where batch_id=%s",
            (bid,),
        )
        assert cur.fetchone() == ("source_full", True, "source_full_time")


def test_evidence_cannot_claim_another_raw_time_or_be_mutated(pg):
    import psycopg2

    bid = publish_odds_times(pg, "2026-09-02T22:30:00Z", [(1, "1x2d", [(1, "02-24 00:21")])])
    evidence_migration(pg)
    with pg.cursor() as cur:
        cur.execute("savepoint invalid")
        with pytest.raises(psycopg2.Error):
            time_evidence(pg, bid, "1/1x2d/0", "2026-02-24T16:21:00Z")
        cur.execute("rollback to savepoint invalid")
    time_evidence(pg, bid, "1/1x2d/0", "2026-02-23T16:21:00Z")
    with pg.cursor() as cur:
        cur.execute("savepoint immutable_evidence")
        for query in (
            "delete from football_history_odds_time_evidence",
            "update football_history_odds_time_evidence set time_basis='inferred_year'",
            "truncate football_history_odds_time_evidence",
        ):
            with pytest.raises(psycopg2.Error):
                cur.execute(query)
            cur.execute("rollback to savepoint immutable_evidence")


def test_source_evidence_still_rejects_a_group_order_conflict(pg):
    bid = publish_odds_times(
        pg,
        "2022-11-22T10:00:00Z",
        [(1, "1x2d", [(1, "11-20 18:00"), (2, "04-02 03:42"), (3, "11-21 18:00")])],
    )
    evidence_migration(pg)
    time_evidence(pg, bid, "1/1x2d/1", "2022-04-01T19:42:00Z", basis="inferred_year")
    with pg.cursor() as cur:
        cur.execute(
            "select bool_or(timeline_usable),min(group_direction) from football_history_odds_timeline"
        )
        assert cur.fetchone() == (False, "conflict")


def test_evidence_import_dry_run_repeat_and_conflict(pg):
    from scripts.titan007_odds_evidence import VERSION
    from scripts.titan007_odds_evidence import import_package as import_times

    bid = publish_odds_times(pg, "2026-09-02T22:30:00Z", [(1, "1x2d", [(1, "02-24 00:21")])])
    evidence_migration(pg)
    with pg.cursor() as cur:
        cur.execute("select value_json from football_history_records")
        raw = cur.fetchone()[0]
    package = {
        "version": VERSION,
        "batch_content_sha256": "a" * 64,
        "counts": {"source_full": 1},
        "rows": [
            {
                "batch_id": bid,
                "source_record_key": "1/1x2d/0",
                "source_match_id": 1,
                "expected_value": {
                    k: raw[k]
                    for k in (
                        "company_id",
                        "odds_type",
                        "source",
                        "seq",
                        "change_time",
                        "home",
                        "line",
                        "away",
                    )
                },
                "change_at": "2026-02-23T16:21:00Z",
                "time_basis": "source_full",
                "effective_kickoff_at": "2026-09-02T22:30:00Z",
                "kickoff_basis": "source_schedule",
                "source_url": "https://1x2d.titan007.com/1.js",
                "response_sha256": "b" * 64,
                "observed_at": "2026-10-29T17:30:00Z",
                "provenance": {"home_team_id": 10, "away_team_id": 20, "source_year": "2026"},
            }
        ],
    }
    pg.commit()
    checked = []

    def verify(cur):
        cur.execute("select bool_and(timeline_usable) ok from football_history_odds_timeline")
        checked.append(cur.fetchone()["ok"])

    assert import_times(pg, package, verify=verify)["status"] == "dry_run"
    assert checked == [True]
    with pg.cursor() as cur:
        cur.execute("select count(*) from football_history_odds_time_evidence")
        assert cur.fetchone()[0] == 0
    assert import_times(pg, package, dry_run=False)["records"] == 1
    assert import_times(pg, package, dry_run=False)["records"] == 1
    package["rows"][0]["response_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="differs"):
        import_times(pg, package, dry_run=False)
    with pg.cursor() as cur:
        cur.execute("select response_sha256 from football_history_odds_time_evidence")
        assert cur.fetchone()[0] == "b" * 64


def test_evidence_builder_checks_frozen_payload_and_raw_values(tmp_path):
    import hashlib

    from scripts.titan007_odds_evidence import build_package

    company = "|".join(["82", "999", "Example"] + ["2"] * 19)
    payload = (
        f'var game=Array("{company}"); var gameDetail=Array("999^2|3|4|12-07 11:11|1|1|1|2023");'
        'var ScheduleID="1"; var hometeamID="10"; var guestteamID="20"; var MatchTime="2024,06-1,17,19,00,00";'
    ).encode()
    (tmp_path / "1.js").write_bytes(payload)
    audit = {
        "finished_at": "2026-10-29T00:00:00Z",
        "matches": [
            {
                "match_id": 1,
                "home_id": 10,
                "away_id": 20,
                "kickoff": "2024-06-18 03:00",
                "payload_sha256": hashlib.sha256(payload).hexdigest(),
                "fetched_file_mtime": "2026-10-29T00:00:00Z",
            }
        ],
        "rows": [
            {
                "match_id": 1,
                "company_id": 82,
                "odds_type": "europe",
                "source": "1x2d",
                "seq": 1,
                "change_time": "12-07 11:11",
                "home": 2.0,
                "line": "3",
                "away": 4.0,
            }
        ],
    }
    path = tmp_path / "verification.json"
    path.write_text(json.dumps(audit))
    package = build_package(path, "a" * 64)
    assert package["rows"][0]["change_at"] == "2023-12-07T03:11:00+00:00"
    audit["rows"][0]["home"] = 2.1
    path.write_text(json.dumps(audit))
    with pytest.raises(ValueError, match="content mismatch"):
        build_package(path, "a" * 64)
    (tmp_path / "1.js").write_bytes(payload + b"\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        build_package(path, "a" * 64)


def test_event_inference_requires_an_anchor_and_consistent_order():
    from datetime import UTC, datetime

    from scripts.titan007_odds_evidence import _context_group

    kickoff = datetime(2022, 11, 22, tzinfo=UTC)
    rows = [{"seq": 1, "change_time_raw": "04-02 03:42"}]
    with pytest.raises(ValueError, match="anchor"):
        _context_group(rows, kickoff)
    rows = [
        {"seq": 1, "change_time_raw": "11-20 03:42"},
        {"seq": 2, "change_time_raw": "04-02 03:42"},
        {"seq": 3, "change_time_raw": "11-21 03:42"},
    ]
    with pytest.raises(ValueError, match="consistent order"):
        _context_group(rows, kickoff)


@pytest.mark.parametrize(
    "dsn,ambient",
    [
        ("host=127.0.0.1 hostaddr=192.0.2.1 dbname=isolated", {}),
        ("host=127.0.0.1 dbname=isolated service=remote", {}),
        ("host=127.0.0.1 dbname=isolated", {"PGHOSTADDR": "192.0.2.1"}),
        ("host=127.0.0.1 dbname=isolated", {"PGSERVICE": "remote"}),
        ("host=127.0.0.1 dbname=isolated", {"PGSERVICEFILE": "/tmp/remote.conf"}),
        ("host=127.0.0.1", {}),
    ],
)
def test_history_cli_rejects_indirect_remote_routes(dsn, ambient, tmp_path, monkeypatch):
    import psycopg2

    from scripts import titan007_history

    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", dsn)
    for key, value in ambient.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("sys.argv", ["history", "--import-package", str(tmp_path)])
    calls = []
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **kw: calls.append((a, kw)))
    with pytest.raises(ValueError, match="loopback"):
        titan007_history.main()
    assert calls == []


@pytest.mark.parametrize("host,address", [("localhost", "127.0.0.1"), ("::1", "::1")])
def test_history_cli_pins_numeric_loopback(host, address, tmp_path, monkeypatch):
    from unittest.mock import MagicMock

    import psycopg2

    from scripts import titan007_history

    for key in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATABASE_URL", f"host={host} dbname=isolated")
    monkeypatch.setattr("sys.argv", ["history", "--import-package", str(tmp_path)])
    connect = MagicMock()
    monkeypatch.setattr(psycopg2, "connect", connect)
    monkeypatch.setattr(titan007_history, "import_package", lambda *a, **kw: {"status": "dry_run"})
    titan007_history.main()
    params = connect.call_args.kwargs
    assert not connect.call_args.args
    assert params["host"] == host and params["hostaddr"] == address


@pytest.mark.parametrize("offset", ["+25:00", "-25:00", "+02:99"])
def test_invalid_explicit_timezone_is_an_unresolved_row(pg, offset):
    publish_odds_times(
        pg,
        "2024-01-01T12:00:00Z",
        [(1, "1x2d", [(1, "2024-01-01T19:00:00" + offset)]), (2, "1x2d", [(1, "01-01 19:00")])],
    )
    evidence_migration(pg)
    with pg.cursor() as cur:
        cur.execute(
            "select change_at,time_basis,time_resolution_reason,timeline_usable from football_history_odds_timeline order by value_json->>'company_id'"
        )
        invalid, valid = cur.fetchall()
    assert invalid == (None, "unresolved", "invalid_timezone_offset", False)
    assert valid[0] is not None and valid[1:] == ("inferred_year", "unique_match_window", True)


def test_timezone_migration_preserves_v2_candidates_and_transaction_rollback(pg):
    import psycopg2

    publish_odds_times(pg, "2024-01-01T12:00:00Z", [(1, "1x2d", [(1, "12-31 23:00")])])
    path = Path(__file__).resolve().parents[3] / "sql/122_football_history_odds_evidence.sql"
    query = (
        "select raw,c.* from unnest(array['12-31 23:00','2023-01-01 19:00',"
        "'2024-01-01T11:00:00+02:00','02-30 12:00','',null]::text[]) raw "
        "cross join lateral football_history_odds_time_candidate(raw,'2024-01-01T12:00:00Z') c"
    )
    with pg.cursor() as cur:
        cur.execute(path.read_text())
        cur.execute(query)
        before = cur.fetchall()
        cur.execute("savepoint timezone_migration")
        cur.execute(path.with_name("123_football_history_odds_invalid_timezone.sql").read_text())
        cur.execute(query)
        assert cur.fetchall() == before
        cur.execute(
            "select proparallel from pg_proc where oid='football_history_odds_time_candidate(text,timestamptz)'::regprocedure"
        )
        assert cur.fetchone()[0] == "u"
        cur.execute("rollback to savepoint timezone_migration")
        with pytest.raises(psycopg2.errors.InvalidTimeZoneDisplacementValue):
            cur.execute(
                "select * from football_history_odds_time_candidate('2024-01-01T19:00:00+25:00','2024-01-01T12:00:00Z')"
            )
        cur.execute("rollback to savepoint timezone_migration")
