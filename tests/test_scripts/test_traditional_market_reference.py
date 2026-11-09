import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import Json

from apps.backend.src.db import get_db
from ops.server.migrate import migration_body
from scripts import sporttery_pool_schedule as pool_schedule
from scripts import traditional_market_reference as collector
from scripts.football_pool_catalog import read_pool_catalog_issue
from scripts.prematch_schedule import BEIJING
from scripts.sporttery_pool_schedule import _store_current_issue, parse_current_issue
from scripts.traditional_market_reference import (
    MarketTarget,
    match_titan_fixture,
    read_current_quote,
)
from tests.test_scripts.test_sporttery_pool_schedule import schedule_response

KICKOFF = datetime.fromisoformat("2026-11-13T01:00:00+08:00")
TARGET = datetime.fromisoformat("2026-11-12T20:30:00+08:00")
FIXTURE = MarketTarget(1, KICKOFF, TARGET, "9345", "欧国联", "主队", "客队")


def fixture_row(**changes):
    return {
        "match_id": 50,
        "league_id": 20,
        "league_name": "欧国联",
        "home_name": "主队",
        "away_name": "客队",
        "kickoff": "2026-11-13 01:00",
        "status_code": 0,
        **changes,
    }


def odds_payload(**changes):
    return {
        "meta": {
            "ScheduleID": "50",
            "MatchTime": "2026,11-1,12,17,00,00",
            "sclassId": "20",
            "hometeam_cn": "主队",
            "guestteam_cn": "客队",
        },
        "companies": [
            {
                "company_id": 20,
                "company_name": "A",
                "change_time": "2026-11-12 12:28:00",
                "live_home": 2.0,
                "live_draw": 3.1,
                "live_away": 4.0,
            },
            {
                "company_id": 21,
                "company_name": "B",
                "change_time": "2026-11-12 12:29:00",
                "live_home": 1.95,
                "live_draw": 3.2,
                "live_away": 4.1,
            },
        ],
        **changes,
    }


def test_titan_schedule_needs_one_exact_unstarted_fixture():
    row = fixture_row()
    assert match_titan_fixture(FIXTURE, [row, row]) == row
    assert match_titan_fixture(FIXTURE, [row, fixture_row(match_id=51)]) is None
    assert match_titan_fixture(FIXTURE, [row, fixture_row(status_code=-14)]) is None
    assert match_titan_fixture(FIXTURE, [fixture_row(home_name="主")]) is None
    assert match_titan_fixture(FIXTURE, [fixture_row(home_name="客队", away_name="主队")]) is None
    assert match_titan_fixture(FIXTURE, [fixture_row(kickoff="2026-11-12 01:00")]) is None


def test_pick_one_complete_recent_bookmaker_group_with_utc_clock():
    quote = read_current_quote(FIXTURE, fixture_row(), odds_payload(), TARGET)
    assert quote["company_id"] == 21
    assert quote["quote_at"] == "2026-11-12T12:29:00+00:00"
    assert quote["odds"] == {"h": 1.95, "d": 3.2, "a": 4.1}
    assert sum(quote["probabilities"].values()) == pytest.approx(1)
    assert read_current_quote(FIXTURE, fixture_row(), odds_payload(), KICKOFF) is None
    assert (
        read_current_quote(FIXTURE, fixture_row(), odds_payload(), TARGET + timedelta(minutes=45))
        is None
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"ScheduleID": "51"},
        {"sclassId": "21"},
        {"hometeam_cn": "客队"},
        {"MatchTime": "2026,11-1,13,01,00,00"},
    ],
)
def test_odds_payload_must_corroborate_schedule(changes):
    payload = odds_payload()
    payload["meta"].update(changes)
    assert read_current_quote(FIXTURE, fixture_row(), payload, TARGET) is None


def test_incomplete_future_and_ambiguous_company_rows_cannot_be_combined():
    payload = odds_payload()
    first, second = payload["companies"]
    assert (
        read_current_quote(
            FIXTURE, fixture_row(), odds_payload(companies=[first, first, second]), TARGET
        )["company_id"]
        == 21
    )
    first["live_draw"] = None
    second["change_time"] = "2026-11-12 12:31:00"
    assert read_current_quote(FIXTURE, fixture_row(), payload, TARGET) is None
    second["change_time"] = "2026-11-12 12:29"
    assert read_current_quote(FIXTURE, fixture_row(), payload, TARGET) is None


def test_due_reference_persists_once_for_both_issues_and_respects_late_replacement(
    monkeypatch, tmp_path
):
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for isolated scheduling tests")
    params = psycopg2.extensions.parse_dsn(dsn)
    assert params["host"] in {"127.0.0.1", "localhost"}
    assert params["dbname"].startswith("fqp_prematch_test")
    assert params["user"] == "fqp" and os.getenv("DATABASE_URL") == dsn

    now = datetime.now(BEIJING).replace(second=0, microsecond=0)
    kickoff = now + timedelta(days=1 + uuid4().int % 6, minutes=uuid4().int % 600)
    amended_kickoff = kickoff + timedelta(minutes=15)
    stop = now - timedelta(days=1)
    source_ids = [
        "8" + str(uuid4().int % 100_000_000_000_000_000).zfill(17),
        "8" + str(uuid4().int % 100_000_000_000_000_000).zfill(17),
    ]
    with get_db() as conn, conn.cursor() as cur:
        while True:
            issue_no = f"20{uuid4().int % 1_000_000:06d}"
            cur.execute(
                "SELECT 1 FROM football_pool_issues WHERE issue_no=%s LIMIT 1",
                (issue_no,),
            )
            if cur.fetchone() is None:
                break
        cur.execute("SELECT count(*) FROM official_matches")
        official_match_count_before = cur.fetchone()[0]
        while True:
            cur.execute(
                "SELECT 1 FROM official_matches WHERE source_match_id=ANY(%s) LIMIT 1",
                (source_ids,),
            )
            if cur.fetchone() is None:
                break
            source_ids = [
                "8" + str(uuid4().int % 100_000_000_000_000_000).zfill(17),
                "8" + str(uuid4().int % 100_000_000_000_000_000).zfill(17),
            ]
    notice_url = f"https://www.sporttery.cn/test-reference-change/{issue_no}"
    with get_db() as conn:
        for code in (90, 900129):
            payload = schedule_response(code, 14, issue_no)
            draw = payload["value"]["drawMatch"]
            draw["lotterySaleBeginTime"] = (now - timedelta(days=2)).isoformat()
            draw["lotterySaleEndTime"] = stop.isoformat()
            for member in draw["matchList"]:
                member["startTime"] = kickoff.date().isoformat()
            draw["matchList"][0]["startTime"] = kickoff.strftime("%Y-%m-%d %H:%M")
            draw["matchList"][0]["gmMatchId"] = source_ids[0]
            draw["matchList"][1]["startTime"] = amended_kickoff.strftime("%Y-%m-%d %H:%M")
            draw["matchList"][1]["gmMatchId"] = source_ids[1]
            assert _store_current_issue(conn, parse_current_issue(code, payload, now)) == (1, 14)
        conn.commit()

    def schedule_row(source_id, home, away, starts):
        return (
            f'<tr id="tr1_{source_id}" sid="{source_id}" name="20,0"><td>欧国联</td>'
            f"<td>{starts:%Y-%m-%d %H:%M}</td><td></td><td>{home}</td><td>-</td>"
            f"<td>{away}</td><td></td><td></td><td></td></tr>"
        )

    def odds_js(source_id, home, away, starts):
        start = starts.astimezone(UTC)
        quoted = (now - timedelta(minutes=1)).astimezone(UTC)
        fields = [""] * 22
        fields[:3] = ["20", "202", "Sample Book"]
        fields[10:13] = ["2.05", "3.20", "3.90"]
        fields[20] = quoted.strftime("%Y,%m-1,%d,%H,%M,%S")
        return (
            f'var ScheduleID="{source_id}"; var sclassId="20";'
            f'var MatchTime="{start:%Y,%m-1,%d,%H,%M,%S}";'
            f'var hometeam_cn="{home}"; var guestteam_cn="{away}";'
            f"var game={json.dumps(['|'.join(fields)])}; var gameDetail=[];"
        )

    class Source:
        def get_bytes(self, url, **kwargs):
            if "Next_" in url:
                html = "<table>" + schedule_row(50, "主队1", "客队1", kickoff)
                html += schedule_row(51, "主队2", "客队2", amended_kickoff) + "</table>"
                return html.encode(), "text/html; charset=utf-8"
            if url.endswith("/50.js"):
                return odds_js(50, "主队1", "客队1", kickoff).encode(), "text/javascript"
            assert url.endswith("/51.js")
            # The replacement arrives while the quote request is in flight.
            with get_db() as conn, conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO sporttery_schedule_notices
                           (source_url,content_sha256,published_at,evidence)
                       VALUES (%s,%s,%s,%s)""",
                    (
                        notice_url,
                        "test-" + issue_no,
                        now,
                        Json(
                            {
                                "kind": "pool_schedule",
                                "source_url": notice_url,
                                "issues": [
                                    {
                                        "game_type": game,
                                        "issue_no": issue_no,
                                        "matches": [
                                            {
                                                "match_order": 1,
                                                "match_date": kickoff.date().isoformat(),
                                                "home_team_name": "主队1",
                                                "away_team_name": "客队1",
                                            },
                                            {
                                                "match_order": 2,
                                                "match_date": amended_kickoff.date().isoformat(),
                                                "home_team_name": "换入主队",
                                                "away_team_name": "换入客队",
                                            },
                                        ],
                                    }
                                    for game in ("t14c", "r9")
                                ],
                            }
                        ),
                    ),
                )
                conn.commit()
            return odds_js(51, "主队2", "客队2", amended_kickoff).encode(), "text/javascript"

    monkeypatch.setattr(collector, "data_directory", lambda: tmp_path / "cache")
    monkeypatch.setattr(collector, "TitanClient", lambda **_: Source())
    monkeypatch.setattr(collector, "_pages", {})
    original_current_targets = collector._current_targets

    def current_test_targets(conn, observed_at, fixture_id=None):
        return {
            target: basis
            for target, basis in original_current_targets(conn, observed_at, fixture_id).items()
            if target.sporttery_id in source_ids
        }

    monkeypatch.setattr(collector, "_current_targets", current_test_targets)
    monkeypatch.setattr(pool_schedule, "_issue_checks", {})
    monkeypatch.setattr(pool_schedule, "_heads", {})
    result = collector.run_due()
    assert result == {"status": "ok", "checked": 2, "published": 1}
    assert collector.run_due() == {"status": "ok", "checked": 0, "published": 0}
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM football_pool_issues WHERE issue_no=%s ORDER BY id", (issue_no,)
        )
        fixtures = [read_pool_catalog_issue(conn, iid)["fixtures"] for (iid,) in cur.fetchall()]
        assert len(fixtures) == 2
        assert fixtures[0][0]["fixture_id"] == fixtures[1][0]["fixture_id"]
        reference = fixtures[0][0]["market_reference"]
        assert fixtures[1][0]["market_reference"] == reference
        assert reference["odds"] == {"h": 2.05, "d": 3.20, "a": 3.90}
        assert reference["company_name"] == "Sample Book"
        assert reference["source_match_id"] == "50"
        assert reference["quote_at"] < reference["published_at"] < fixtures[0][0]["kickoff"]
        assert all(group[1]["market_reference"] is None for group in fixtures)
        cur.execute("SELECT count(*) FROM official_matches")
        assert cur.fetchone() == (official_match_count_before,)
        cur.execute(
            "SELECT checks,schedule_basis FROM football_fixture_market_references "
            "WHERE published_at IS NOT NULL"
        )
        checks, basis = cur.fetchone()
        assert checks == 1 and basis["timing"] == "late_dispatch"
        assert {scope["game_type"] for scope in basis["scopes"]} == {"t14c", "r9"}
        with pytest.raises(psycopg2.errors.RaiseException):
            cur.execute("UPDATE football_fixture_market_references SET checks=2")
        conn.rollback()


def test_migration_133_rollback_preserves_published_market_reference():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for isolated migration rehearsal")
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    assert parsed["user"] == "fqp" and os.getenv("DATABASE_URL") == dsn

    schema = "market_reference_down_" + uuid4().hex
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE football_fixtures(id BIGINT PRIMARY KEY)")
            cur.execute(
                """CREATE FUNCTION protect_football_fixture_identity() RETURNS trigger
                   LANGUAGE plpgsql AS $body$ BEGIN RETURN NEW; END $body$"""
            )
            project_root = Path(__file__).resolve().parents[2]
            up = (project_root / "sql/133_traditional_market_reference.sql").read_text()
            down = (project_root / "sql/down/133_traditional_market_reference.down.sql").read_text()
            cur.execute(migration_body(up))
            cur.execute("INSERT INTO football_fixtures VALUES (1)")
            cur.execute(
                """INSERT INTO football_fixture_market_references
                       (fixture_id,kickoff_at,target_at,schedule_basis)
                   VALUES (1,%s,%s,'{}')""",
                (datetime.now(UTC) + timedelta(hours=3), datetime.now(UTC) + timedelta(hours=2)),
            )
            cur.execute("SAVEPOINT before_reference_down")
            with pytest.raises(psycopg2.errors.RaiseException, match="Market references"):
                cur.execute(migration_body(down))
            cur.execute("ROLLBACK TO SAVEPOINT before_reference_down")
            cur.execute("SELECT count(*) FROM football_fixture_market_references")
            assert cur.fetchone() == (1,)
            cur.execute("DELETE FROM football_fixture_market_references")
            cur.execute(migration_body(down))
            cur.execute("SELECT to_regclass('football_fixture_market_references')")
            assert cur.fetchone() == (None,)
        conn.rollback()
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()
