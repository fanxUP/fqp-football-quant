import hashlib
import os
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import Json

from apps.backend.src.db import get_db
from apps.backend.src.services.match_review import build_match_review_cards
from ops.server.migrate import migration_body
from scripts.business_time import business_now
from scripts.jobs.run_model_prediction import run_due
from scripts.model_prediction_run_storage import create_prediction_run, finalize_prediction_run
from scripts.official_crawler import parse_odds_snapshots_from_match
from scripts.prediction_input_updates import InputUpdateSuperseded
from scripts.prematch_schedule import (
    PredictionTask,
    attach_prediction_tasks,
    complete_prediction_tasks,
    current_official_quote,
    due_prediction_tasks,
    fence_scheduled_match,
    jc_sales_cutoff,
    prediction_target,
    reserve_prediction_quotes,
)
from scripts.sporttery_schedule_notices import _store_notices, parse_jc_bulletin


def _unique_display_code(conn, business_date, reserved=()):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT official_match_code FROM official_matches WHERE business_date=%s",
            (business_date,),
        )
        used = {row[0] for row in cur.fetchall()} | set(reserved)
    return next(code for number in range(1000) if (code := f"周一{number:03d}") not in used)


@pytest.mark.parametrize(
    ("kickoff", "cutoff", "target"),
    [
        ("2026-11-09T19:00", "2026-11-09T22:00", "2026-11-09T17:00:00+08:00"),
        ("2026-11-10T02:00", "2026-11-09T22:00", "2026-11-09T20:30:00+08:00"),
        ("2027-01-01T02:00", "2026-12-31T22:00", "2026-12-31T20:30:00+08:00"),
        ("2026-11-09T22:00", "2026-11-09T22:00", "2026-11-09T20:00:00+08:00"),
        ("2026-11-09T19:00", "2026-11-09T18:00", "2026-11-08T20:30:00+08:00"),
        ("2026-11-09T18:00", None, "2026-11-09T16:00:00+08:00"),
    ],
)
def test_prediction_target(kickoff, cutoff, target):
    actual, _ = prediction_target(
        datetime.fromisoformat(kickoff), datetime.fromisoformat(cutoff) if cutoff else None
    )
    assert actual.isoformat() == target


def test_official_bulletin_retains_date_and_scope():
    published, value = parse_jc_bulletin(
        {
            "bulletinId": "2079400",
            "bulletinStarttime": "2026-11-09 10:00:00",
            "bulletinSubject": "11月9日销售安排",
            "bulletinContent": "11月9日竞彩游戏开售时间为11:00,停售时间为22:00。请广大购彩者关注。",
        }
    )
    assert published.isoformat() == "2026-11-09T10:00:00+08:00"
    assert value["cutoff"] == "2026-11-09T22:00:00+08:00"
    assert value["kind"] == "jc_sales_window"


def test_cancelled_bulletin_carries_exact_teams_and_display_code():
    _, value = parse_jc_bulletin(
        {
            "bulletinId": "2079400",
            "bulletinStarttime": "2026-11-07 09:18:00",
            "bulletinSubject": "周六 018比赛取消竞猜",
            "bulletinContent": "周六 018 挪威超级联赛“克里斯蒂安松 VS 瓦勒伦加”因球队原因,取消该场比赛竞猜。",
        }
    )
    assert (value["match_code"], value["home"], value["away"], value["state"]) == (
        "周六018",
        "克里斯蒂安松",
        "瓦勒伦加",
        "withdrawn",
    )


def test_changed_bulletin_normalizes_kickoff_to_the_precision_used_by_the_fence():
    _, value = parse_jc_bulletin(
        {
            "bulletinId": "2079401",
            "bulletinStarttime": "2026-11-07 09:18:00",
            "bulletinSubject": "周六 018 比赛推迟",
            "bulletinContent": "周六 018 挪超“克里斯蒂安松 VS 瓦勒伦加”比赛推迟至11月8日20:30。",
        }
    )
    assert value["kickoff"] == "2026-11-08T20:30:00"


def test_suspended_quote_is_fresh_and_cannot_be_used_for_ticket():
    raw = {
        "sellStatus": 2,
        "poolList": [{"poolCode": "HAD", "poolStatus": "Paused", "single": 1}],
        "had": {
            "h": "1.90",
            "d": "3.25",
            "a": "3.70",
            "updateDate": "2026-11-09",
            "updateTime": "20:15",
        },
    }
    assert parse_odds_snapshots_from_match(raw, "2026-11-09T20:30:00") == []
    valid = parse_odds_snapshots_from_match(raw, "2026-11-09T20:30:00", prediction_quote=True)
    assert {row["option_code"] for row in valid} == {"h", "d", "a"}
    assert all(not row["is_open"] and not row["is_single_allowed"] for row in valid)
    assert parse_odds_snapshots_from_match(raw, "2026-11-09T22:00:00", prediction_quote=True) == []


def test_isolated_postgres_late_addition_retries_and_withdrawal():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for the isolated scheduling test")
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    conn = psycopg2.connect(dsn)
    # Pick an unused future date so repeat runs never reuse stale test quotes.
    business_date = date(2040, 11, 10)
    with conn.cursor() as cur:
        while True:
            cur.execute(
                "SELECT EXISTS(SELECT 1 FROM official_matches WHERE business_date=%s)",
                (business_date,),
            )
            if not cur.fetchone()[0]:
                break
            business_date += timedelta(days=1)
    now = datetime.fromisoformat(f"{business_date.isoformat()}T21:00:00+08:00")
    base_code = _unique_display_code(conn, business_date)
    late_code = _unique_display_code(conn, business_date, {base_code})
    base_source_id = "prematch-base-" + uuid4().hex[:10]
    late_source_id = "prematch-late-" + uuid4().hex[:10]
    late_home = "Late H " + uuid4().hex[:6]
    late_away = "Late A " + uuid4().hex[:6]
    notice_url = "isolated-test://" + uuid4().hex
    notice_digest = hashlib.sha256(notice_url.encode()).hexdigest()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO official_matches
                (business_date,official_match_code,source_match_id,league_name,home_team_name,away_team_name,
                 kickoff_time,sale_status,created_at)
                VALUES (%s,%s,%s,'test','Base H','Base A',%s,'closed',%s),
                       (%s,%s,%s,'test',%s,%s,%s,'closed',%s)
                RETURNING id, source_match_id""",
                (
                    business_date,
                    base_code,
                    base_source_id,
                    f"{business_date.isoformat()} 23:15",
                    f"{business_date.isoformat()} 10:00",
                    business_date,
                    late_code,
                    late_source_id,
                    late_home,
                    late_away,
                    f"{business_date + timedelta(days=1)} 02:00",
                    f"{business_date.isoformat()} 12:50",
                ),
            )
            ids = {source: mid for mid, source in cur.fetchall()}
            mid = ids[late_source_id]
            cur.execute(
                "INSERT INTO official_markets(match_id,play_type,is_open) VALUES (%s,'spf',false)",
                (mid,),
            )
        conn.commit()
        tasks, _ = due_prediction_tasks(conn, now)
        assert not tasks
        assert [row[0] for row in reserve_prediction_quotes(conn, now)] == [mid]
        assert not reserve_prediction_quotes(conn, now)
        with conn.cursor() as cur:
            for capture, options in (("complete", "hda"), ("split1", "hd"), ("split2", "a")):
                stamp = (
                    f"{business_date.isoformat()} 20:56"
                    if capture == "complete"
                    else f"{business_date.isoformat()} 20:57"
                )
                for option in options:
                    cur.execute(
                        """INSERT INTO official_odds_snapshots
                         (match_id,snapshot_time,play_type,option_code,option_name,sp_value,is_open,raw_json,raw_hash,created_at)
                       VALUES (%s,%s,'spf',%s,%s,2.6,false,%s,%s,%s)""",
                        (
                            mid,
                            stamp,
                            option,
                            option,
                            Json(
                                {
                                    "_collector_timezone": "Asia/Shanghai",
                                    "_capture_purpose": "prediction_quote",
                                }
                            ),
                            capture,
                            f"{business_date.isoformat()} 12:58",
                        ),
                    )
        conn.commit()
        quote = current_official_quote(conn, mid, "spf", f"{business_date.isoformat()} 21:00")
        assert len(quote) == 3 and {row[3].minute for row in quote} == {56}
        tasks, manifest = due_prediction_tasks(conn, now)
        assert len(tasks) == 1
        assert manifest[0]["timing"] == "added_after_target"
        assert manifest[0]["target_at"] == f"{business_date.isoformat()}T20:30:00+08:00"
        run = uuid4()
        create_prediction_run(
            conn,
            run_id=run,
            ai_job_run_id=None,
            release_id="isolated-test",
            code_fingerprint={},
            model_manifest=[],
            input_manifest={},
            provenance_status="incomplete",
        )
        attach_prediction_tasks(conn, tasks, run)
        finalize_prediction_run(
            conn,
            run_id=run,
            run_status="completed",
            commit=False,
            output_summary={
                "expected_groups": 0,
                "completed_groups": 0,
                "skipped_groups": 0,
                "input_updates_skipped": 0,
                "missing_groups": [],
                "completion_reason": "no_matches",
            },
        )
        complete_prediction_tasks(conn, run)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT completed_at FROM prematch_prediction_tasks WHERE task_key=%s",
                (tasks[0].key,),
            )
            assert cur.fetchone()[0] is None  # a successful empty run is not a prediction
            cur.execute(
                """INSERT INTO sporttery_schedule_notices(source_url,content_sha256,published_at,evidence)
                           VALUES (%s,%s,%s,%s)""",
                (
                    notice_url,
                    notice_digest,
                    f"{business_date.isoformat()} 12:59+00",
                    Json(
                        {
                            "kind": "jc_fixture_change",
                            "match_code": late_code,
                            "home": late_home,
                            "away": late_away,
                            "state": "withdrawn",
                            "kickoff": None,
                        }
                    ),
                ),
            )
        conn.commit()
        assert due_prediction_tasks(conn, now + timedelta(minutes=1)) == ([], [])
    finally:
        conn.rollback()
        conn.close()


def test_isolated_scheduled_prediction_can_run_without_sale_or_feature_evidence():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for the isolated scheduling test")
    assert dsn == os.environ["DATABASE_URL"]
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    now = business_now()
    local = now.replace(tzinfo=None)
    day = now.date() - timedelta(days=1)
    code_conn = psycopg2.connect(dsn)
    try:
        match_code = _unique_display_code(code_conn, day)
    finally:
        code_conn.close()
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches
                          (business_date,official_match_code,source_match_id,league_name,home_team_name,
                           away_team_name,kickoff_time,sale_status)
                       VALUES (%s,%s,%s,'Fixture Test','Test H','Test A',%s,'closed') RETURNING id""",
            (day, match_code, "prematch-e2e-" + uuid4().hex[:10], local + timedelta(hours=1)),
        )
        mid = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO official_markets(match_id,play_type,is_open) VALUES (%s,'spf',false)",
            (mid,),
        )
        for option, price in zip("hda", (1.9, 3.2, 4.2), strict=True):
            cur.execute(
                """INSERT INTO official_odds_snapshots
                           (match_id,snapshot_time,play_type,option_code,option_name,sp_value,is_open,
                            raw_json,raw_hash,created_at)
                           VALUES (%s,%s,'spf',%s,%s,%s,false,%s,'one-capture',now()-INTERVAL '2 minutes')""",
                (
                    mid,
                    local - timedelta(minutes=2),
                    option,
                    option,
                    price,
                    Json(
                        {
                            "_collector_timezone": "Asia/Shanghai",
                            "_capture_purpose": "prediction_quote",
                        }
                    ),
                ),
            )
        conn.commit()
    assert run_due()["predictions"] >= 3
    assert run_due()["due"] == 0
    with get_db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT t.completed_at,r.input_manifest->'prematch_schedule'
                       FROM prematch_prediction_tasks t JOIN model_prediction_runs r ON r.id=t.run_id
                       WHERE t.match_id=%s""",
            (mid,),
        )
        completed, manifest = cur.fetchone()
        assert completed and manifest[0]["target_at"].split("T")[1].startswith("20:30")
        cur.execute(
            """INSERT INTO official_results(match_id,full_home_goals,full_away_goals,spf_result,result_status)
                       VALUES (%s,2,1,'3','confirmed')""",
            (mid,),
        )
        conn.commit()
        cards = build_match_review_cards(conn, day.isoformat())
    card = next(item for item in cards if item["matchId"] == mid)
    assert card["oddsComparisonStatus"] == "cutoff_unknown" and not card["oddsSignals"]
    assert any(item["predictionOddsSnapshotId"] for item in card["modelSignals"])


def test_migration_132_rollback_refuses_to_delete_schedule_receipts():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for the isolated migration rehearsal")
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    assert parsed["user"] == "fqp" and os.getenv("DATABASE_URL") == dsn

    schema = "prematch_down_" + uuid4().hex
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE official_matches(id BIGINT PRIMARY KEY)")
            cur.execute("CREATE TABLE model_prediction_runs(id UUID PRIMARY KEY)")
            cur.execute(
                """CREATE TABLE match_feature_snapshots(
                       home_team_id BIGINT NOT NULL, away_team_id BIGINT NOT NULL,
                       feature_version TEXT NOT NULL)"""
            )
            up = (
                Path(__file__).resolve().parents[2] / "sql/132_prematch_prediction_schedule.sql"
            ).read_text()
            down = (
                Path(__file__).resolve().parents[2]
                / "sql/down/132_prematch_prediction_schedule.down.sql"
            ).read_text()
            cur.execute(migration_body(up))
            cur.execute("INSERT INTO official_matches VALUES (1)")
            cur.execute(
                """INSERT INTO prematch_prediction_tasks
                       (task_key,match_id,play_type,kickoff_at,target_at,schedule_basis)
                   VALUES ('receipt',1,'spf',%s,%s,'{}')""",
                (
                    datetime.now(UTC) + timedelta(hours=3),
                    datetime.now(UTC) + timedelta(hours=2),
                ),
            )
            cur.execute(
                """INSERT INTO sporttery_schedule_notices
                       (source_url,content_sha256,published_at,evidence)
                   VALUES ('https://www.sporttery.cn/test','receipt',%s,'{}')""",
                (datetime.now(UTC),),
            )
            cur.execute("SAVEPOINT before_down")
            with pytest.raises(psycopg2.errors.RaiseException, match="Schedule receipts"):
                cur.execute(migration_body(down))
            cur.execute("ROLLBACK TO SAVEPOINT before_down")
            cur.execute("SELECT count(*) FROM prematch_prediction_tasks")
            assert cur.fetchone() == (1,)
            cur.execute("SELECT count(*) FROM sporttery_schedule_notices")
            assert cur.fetchone() == (1,)
        conn.rollback()
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


def test_fixture_change_notice_and_prediction_fence_share_transaction_lock():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for the isolated scheduling test")
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    assert parsed["user"] == "fqp" and os.getenv("DATABASE_URL") == dsn

    source_id = "lock-" + uuid4().hex[:10]
    source_url = "isolated-test://" + source_id
    now = business_now()
    kickoff = now + timedelta(hours=2)
    mid = None
    reader = psycopg2.connect(dsn)
    try:
        match_code = _unique_display_code(reader, kickoff.date())
        with reader.cursor() as cur:
            cur.execute(
                """INSERT INTO official_matches
                       (business_date,official_match_code,source_match_id,league_name,
                        home_team_name,away_team_name,kickoff_time,sale_status,match_status)
                   VALUES (%s,%s,%s,'Fixture Test','Lock H','Lock A',%s,'selling','scheduled')
                   RETURNING id""",
                (
                    kickoff.date(),
                    match_code,
                    source_id,
                    kickoff.replace(tzinfo=None),
                ),
            )
            mid = cur.fetchone()[0]
        reader.commit()

        task = PredictionTask(
            mid,
            "spf",
            kickoff,
            kickoff - timedelta(hours=2),
            {
                "source_match_id": source_id,
                "home": "Lock H",
                "away": "Lock A",
            },
        )
        # Holding the publication fence must keep the concurrent bulletin writer out
        # until this prediction transaction commits.
        fence_scheduled_match(reader, task)
        started = threading.Event()
        finished = threading.Event()
        errors: list[BaseException] = []

        def publish_notice():
            started.set()
            try:
                published = datetime.now(UTC)
                _store_notices(
                    [
                        (
                            published,
                            {
                                "source_url": source_url,
                                "kind": "jc_fixture_change",
                                "match_code": match_code,
                                "home": "Lock H",
                                "away": "Lock A",
                                "state": "changed",
                                "kickoff": (kickoff + timedelta(days=1))
                                .replace(tzinfo=None)
                                .isoformat(timespec="seconds"),
                            },
                        )
                    ]
                )
            except BaseException as exc:
                errors.append(exc)
            finally:
                finished.set()

        writer = threading.Thread(target=publish_notice, daemon=True)
        writer.start()
        assert started.wait(2), "notice writer did not start"
        assert not finished.wait(0.3), "notice writer bypassed the held prediction fence"
        reader.commit()
        writer.join(timeout=5)
        assert finished.is_set(), "notice writer remained blocked after fence commit"
        assert not errors, errors

        with pytest.raises(InputUpdateSuperseded, match="schedule changed"):
            fence_scheduled_match(reader, task)
        reader.rollback()
    finally:
        reader.rollback()
        if mid is not None:
            with reader.cursor() as cur:
                cur.execute(
                    "DELETE FROM sporttery_schedule_notices WHERE source_url=%s", (source_url,)
                )
                cur.execute("DELETE FROM official_matches WHERE id=%s", (mid,))
            reader.commit()
        reader.close()


def test_sales_window_change_invalidates_a_previously_selected_target():
    dsn = os.getenv("FQP_PREMATCH_TEST_DSN")
    if not dsn:
        pytest.skip("set FQP_PREMATCH_TEST_DSN for the isolated scheduling test")
    parsed = psycopg2.extensions.parse_dsn(dsn)
    assert parsed["host"] in {"127.0.0.1", "localhost"}
    assert parsed["dbname"].startswith("fqp_prematch_test")
    assert parsed["user"] == "fqp" and os.getenv("DATABASE_URL") == dsn

    source_id = "cutoff-" + uuid4().hex[:10]
    source_url = "https://www.sporttery.cn/ssgg/test-" + uuid4().hex
    now = business_now()
    kickoff = now + timedelta(hours=2)
    mid = None
    conn = psycopg2.connect(dsn)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO official_matches
                       (business_date,official_match_code,source_match_id,league_name,
                        home_team_name,away_team_name,kickoff_time,sale_status,match_status)
                   VALUES (%s,%s,%s,'Fixture Test','Cutoff H','Cutoff A',%s,'selling','scheduled')
                   RETURNING id""",
                (
                    kickoff.date(),
                    _unique_display_code(conn, kickoff.date()),
                    source_id,
                    kickoff.replace(tzinfo=None),
                ),
            )
            mid = cur.fetchone()[0]
        conn.commit()

        task = PredictionTask(
            mid,
            "spf",
            kickoff,
            kickoff - timedelta(hours=2),
            {
                "source_match_id": source_id,
                "home": "Cutoff H",
                "away": "Cutoff A",
                "source": "sporttery_jc_sales_hours",
                "cutoff": jc_sales_cutoff(kickoff.date()).isoformat(),
            },
        )
        fence_scheduled_match(conn, task)
        conn.commit()
        _store_notices(
            [
                (
                    datetime.now(UTC),
                    {
                        "source_url": source_url,
                        "kind": "jc_sales_window",
                        "business_date": kickoff.date().isoformat(),
                        "cutoff": (kickoff - timedelta(hours=1)).isoformat(),
                    },
                )
            ]
        )
        with pytest.raises(InputUpdateSuperseded, match="sales window changed"):
            fence_scheduled_match(conn, task)
    finally:
        conn.rollback()
        if mid is not None:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM sporttery_schedule_notices WHERE source_url=%s", (source_url,)
                )
                cur.execute("DELETE FROM official_matches WHERE id=%s", (mid,))
            conn.commit()
        conn.close()
