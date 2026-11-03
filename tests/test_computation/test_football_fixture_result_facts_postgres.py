"""PostgreSQL contract tests for immutable, shared football result facts."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import monotonic, sleep

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.errors import CheckViolation, InsufficientPrivilege, RaiseException
from psycopg2.extras import Json

pytest_plugins = ("tests.test_computation.test_football_fixture_identity_postgres",)

ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "sql/130_football_fixture_result_facts.sql"


@pytest.fixture
def result_ready(ready):
    conn = ready
    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text())
    conn.commit()
    return conn


def _fixture_source(conn, *, fixture_id=None, source_match_id="titan-1001"):
    with conn.cursor() as cur:
        if fixture_id is None:
            cur.execute("INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")
            fixture_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_fixture_source_links
               (source_name,id_system,source_match_id,fixture_id,evidence)
               VALUES ('titan007','history.matchId',%s,%s,'{}')
               RETURNING fixture_id""",
            (source_match_id, fixture_id),
        )
    conn.commit()
    return fixture_id


def _fact(fixture_id, *, source_match_id="titan-1001", **changes):
    fact = {
        "fixture_id": fixture_id,
        "source_name": "titan007",
        "id_system": "history.matchId",
        "source_match_id": source_match_id,
        "actual_match_date": "2022-03-19",
        "actual_kickoff_at": None,
        "kickoff_time_precision": "date_only",
        "match_status": "completed",
        "score_basis": "on_field",
        "score_period": "regulation",
        "half_home_goals": 0,
        "half_away_goals": 0,
        "full_home_goals": 0,
        "full_away_goals": 2,
        "source_published_at": None,
        "source_payload": {"id": source_match_id, "score": "0-2", "status": "finished"},
        "evidence": {
            "contract": "football-match-result-fact/v1",
            "identity": {
                "fixture_id": fixture_id,
                "source_name": "titan007",
                "id_system": "history.matchId",
                "source_match_id": source_match_id,
            },
            "source_reference": {"snapshot_sha256": "a" * 64, "record_id": source_match_id},
        },
    }
    fact.update(changes)
    return fact


def _rows(conn, query, params=()):
    with conn.cursor() as cur:
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        return cur.fetchall()


def _insert_fact_direct(conn, fact):
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO football_fixture_result_facts (
                fixture_id,source_name,id_system,source_match_id,
                actual_match_date,actual_kickoff_at,kickoff_time_precision,
                match_status,score_basis,score_period,
                half_home_goals,half_away_goals,full_home_goals,full_away_goals,
                source_published_at,source_payload,evidence
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                fact["fixture_id"],
                fact["source_name"],
                fact["id_system"],
                fact["source_match_id"],
                fact["actual_match_date"],
                fact["actual_kickoff_at"],
                fact["kickoff_time_precision"],
                fact["match_status"],
                fact["score_basis"],
                fact["score_period"],
                fact["half_home_goals"],
                fact["half_away_goals"],
                fact["full_home_goals"],
                fact["full_away_goals"],
                fact["source_published_at"],
                Json(fact["source_payload"]),
                Json(fact["evidence"]),
            ),
        )


def test_store_result_fact_is_idempotent_and_appends_changed_source_payload(result_ready):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    fixture_id = _fixture_source(conn)
    first = store_result_fact(conn, _fact(fixture_id))
    replay = store_result_fact(conn, _fact(fixture_id))
    changed = store_result_fact(
        conn,
        _fact(
            fixture_id,
            source_payload={"id": "titan-1001", "score": "1-2", "status": "finished"},
            full_home_goals=1,
        ),
    )
    conn.commit()

    assert first["inserted"] is True
    assert replay["inserted"] is False
    assert replay["id"] == first["id"]
    assert first["source_payload_sha256"] == replay["source_payload_sha256"]
    assert changed["inserted"] is True
    assert changed["id"] != first["id"]
    assert changed["source_payload_sha256"] != first["source_payload_sha256"]
    assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(2,)]


def test_same_source_payload_with_conflicting_facts_or_evidence_is_rejected(result_ready):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    fixture_id = _fixture_source(conn)
    store_result_fact(conn, _fact(fixture_id))
    conn.commit()

    wrong_score = _fact(fixture_id, full_home_goals=1)
    wrong_evidence = _fact(fixture_id)
    wrong_evidence["evidence"]["source_reference"]["snapshot_sha256"] = "b" * 64

    for inconsistent in (wrong_score, wrong_evidence):
        with pytest.raises(ValueError, match="same source payload has conflicting"):
            store_result_fact(conn, inconsistent)
        conn.rollback()

    assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(1,)]
    assert _rows(conn, "SELECT full_home_goals FROM football_fixture_result_facts") == [(0,)]


def test_concurrent_replay_of_same_source_payload_returns_existing_fact(result_ready):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    fixture_id = _fixture_source(conn)
    fact = _fact(fixture_id)
    first = store_result_fact(conn, fact)
    schema = _rows(conn, "SELECT current_schema()")[0][0]
    concurrent = psycopg2.connect(
        os.environ["FQP_HISTORY_TEST_DSN"], options=f"-c search_path={schema}"
    )
    try:
        backend_pid = _rows(concurrent, "SELECT pg_backend_pid()")[0][0]
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(store_result_fact, concurrent, fact)
            deadline = monotonic() + 10
            waiting_on_conflict = False
            while monotonic() < deadline and not pending.done():
                wait_state = _rows(
                    conn,
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s",
                    (backend_pid,),
                )
                if wait_state and wait_state[0][0] == "Lock":
                    waiting_on_conflict = True
                    break
                sleep(0.01)

            conn.commit()
            replay = pending.result(timeout=10)

        assert waiting_on_conflict is True
        assert first["inserted"] is True
        assert replay["inserted"] is False
        assert replay["id"] == first["id"]
        concurrent.commit()
        assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(1,)]
    finally:
        concurrent.rollback()
        concurrent.close()


@pytest.mark.parametrize(
    ("match_status", "score_basis", "score_period", "eligible"),
    [
        ("completed", "on_field", "regulation", True),
        ("shortened", "on_field", "regulation", False),
        ("abandoned", "on_field", "unknown", False),
        ("postponed", "unknown", "unknown", False),
        ("cancelled", "awarded", "unknown", False),
        ("awarded", "awarded", "regulation", False),
        ("completed", "on_field", "unknown", False),
        ("completed", "on_field", "extra_time", False),
    ],
)
def test_model_result_view_excludes_nonstandard_or_unknown_facts(
    result_ready, match_status, score_basis, score_period, eligible
):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    fixture_id = _fixture_source(conn, source_match_id=f"titan-{match_status}-{score_period}")
    fact = _fact(
        fixture_id,
        source_match_id=f"titan-{match_status}-{score_period}",
        match_status=match_status,
        score_basis=score_basis,
        score_period=score_period,
    )
    stored = store_result_fact(conn, fact)
    conn.commit()

    assert stored["model_eligible"] is eligible
    assert _rows(
        conn,
        "SELECT count(*) FROM football_fixture_model_result_facts WHERE fixture_id=%s",
        (fixture_id,),
    ) == [(1 if eligible else 0,)]


def test_model_result_view_excludes_fact_without_actual_match_date(result_ready):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    source_id = "titan-no-date"
    fixture_id = _fixture_source(conn, source_match_id=source_id)
    fact = _fact(
        fixture_id,
        source_match_id=source_id,
        actual_match_date=None,
        kickoff_time_precision="unknown",
    )
    stored = store_result_fact(conn, fact)
    conn.commit()

    assert stored["model_eligible"] is False
    assert _rows(
        conn,
        "SELECT count(*) FROM football_fixture_model_result_facts WHERE fixture_id=%s",
        (fixture_id,),
    ) == [(0,)]


def test_result_fact_rejects_source_link_bound_to_a_different_fixture(result_ready):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    linked_fixture = _fixture_source(conn, source_match_id="titan-linked")
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute("INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")
        other_fixture = cur.fetchone()[0]
    conn.commit()

    with pytest.raises(ValueError, match="not bound to fixture_id"):
        store_result_fact(conn, _fact(other_fixture, source_match_id="titan-linked"))
    conn.rollback()
    mismatched = _fact(other_fixture, source_match_id="titan-linked")
    with pytest.raises(RaiseException, match="not bound to this shared fixture"):
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO football_fixture_result_facts (
                    fixture_id,source_name,id_system,source_match_id,
                    actual_match_date,kickoff_time_precision,match_status,score_basis,score_period,
                    half_home_goals,half_away_goals,full_home_goals,full_away_goals,
                    source_payload,evidence
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    other_fixture,
                    mismatched["source_name"],
                    mismatched["id_system"],
                    mismatched["source_match_id"],
                    mismatched["actual_match_date"],
                    mismatched["kickoff_time_precision"],
                    mismatched["match_status"],
                    mismatched["score_basis"],
                    mismatched["score_period"],
                    mismatched["half_home_goals"],
                    mismatched["half_away_goals"],
                    mismatched["full_home_goals"],
                    mismatched["full_away_goals"],
                    Json(mismatched["source_payload"]),
                    Json(mismatched["evidence"]),
                ),
            )
    conn.rollback()
    assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(0,)]
    assert linked_fixture != other_fixture


@pytest.mark.parametrize(
    "changes",
    [
        {"half_away_goals": None},
        {"full_home_goals": -1},
        {"match_status": "completed", "score_basis": "awarded"},
        {"actual_kickoff_at": "2022-03-19T03:30:00", "kickoff_time_precision": "minute"},
        {"actual_match_date": None, "kickoff_time_precision": "date_only"},
    ],
)
def test_result_fact_validation_rejects_ambiguous_or_malformed_values(result_ready, changes):
    from scripts.football_fixture_result_facts import store_result_fact

    conn = result_ready
    fixture_id = _fixture_source(conn, source_match_id="titan-invalid")
    with pytest.raises(ValueError):
        store_result_fact(conn, _fact(fixture_id, source_match_id="titan-invalid", **changes))
    conn.rollback()
    assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(0,)]


def test_database_rejects_incomplete_score_pairs(result_ready):
    conn = result_ready
    fixture_id = _fixture_source(conn)
    fact = _fact(fixture_id, half_away_goals=None)
    with pytest.raises(CheckViolation, match="check constraint"):
        _insert_fact_direct(conn, fact)
    conn.rollback()


@pytest.mark.parametrize(
    "changes",
    [
        {"actual_match_date": None, "kickoff_time_precision": "date_only"},
        {"match_status": "completed", "score_basis": "awarded"},
    ],
)
def test_database_rejects_invalid_date_and_awarded_score_semantics(result_ready, changes):
    conn = result_ready
    source_id = "titan-invalid-db-fact"
    fixture_id = _fixture_source(conn, source_match_id=source_id)
    fact = _fact(fixture_id, source_match_id=source_id, **changes)

    with pytest.raises(CheckViolation, match="check constraint"):
        _insert_fact_direct(conn, fact)
    conn.rollback()
    assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(0,)]


def test_runtime_role_can_append_and_read_but_cannot_mutate_or_truncate(result_ready):
    conn = result_ready
    fixture_id = _fixture_source(conn, source_match_id="titan-acl")
    fact = _fact(fixture_id, source_match_id="titan-acl")
    schema = _rows(conn, "SELECT current_schema()")[0][0]
    fact_table = sql.Identifier(schema, "football_fixture_result_facts")

    with conn.cursor() as cur:
        cur.execute(sql.SQL("GRANT USAGE ON SCHEMA {} TO fqp").format(sql.Identifier(schema)))
        cur.execute("SET LOCAL ROLE fqp")
    from scripts.football_fixture_result_facts import store_result_fact

    stored = store_result_fact(conn, fact)
    conn.commit()
    assert stored["inserted"] is True

    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    with pytest.raises(InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("UPDATE {} SET evidence=evidence").format(fact_table))
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    with pytest.raises(InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DELETE FROM {}").format(fact_table))
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE fqp")
    with pytest.raises(InsufficientPrivilege):
        with conn.cursor() as cur:
            cur.execute(sql.SQL("TRUNCATE {}").format(fact_table))
    conn.rollback()

    with conn.cursor() as cur:
        cur.execute(sql.SQL("SET LOCAL ROLE fqp"))
        cur.execute(sql.SQL("SELECT count(*) FROM {}").format(fact_table))
        assert cur.fetchone() == (1,)
    conn.commit()


def test_result_fact_migration_rolls_back_as_one_transaction(ready):
    conn = ready
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO official_matches(
                   business_date,official_match_code,source_match_id,league_name,
                   home_team_name,away_team_name,kickoff_time
               ) VALUES ('2022-03-19','周六001','official-p136-1','固定样本联赛',
                   '主队','客队','2022-03-19 15:00:00') RETURNING id"""
        )
        official_match_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO official_results(
                   match_id,half_home_goals,half_away_goals,full_home_goals,full_away_goals,
                   score_result,result_status,raw_json
               ) VALUES (%s,0,0,0,2,'0:2','confirmed','{"source":"fixed"}')""",
            (official_match_id,),
        )
        cur.execute(
            "INSERT INTO football_pool_issues(issue_no,game_type) VALUES ('P136-KEEP','t14c') RETURNING id"
        )
        issue_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_pool_issue_matches(
                   issue_id,match_order,match_id,league_name,home_team_name,away_team_name,kickoff_time
               ) VALUES (%s,1,%s,'固定样本联赛','主队','客队','2022-03-19 15:00:00')""",
            (issue_id, official_match_id),
        )
        cur.execute("INSERT INTO football_fixtures DEFAULT VALUES RETURNING id")
        fixture_id = cur.fetchone()[0]
        cur.execute(
            """INSERT INTO football_fixture_source_links
                   (source_name,id_system,source_match_id,fixture_id,evidence)
               VALUES ('titan007','history.matchId','titan-p136-keep',%s,'{"source":"fixed"}')""",
            (fixture_id,),
        )
    conn.commit()

    before = _rows(
        conn,
        """SELECT table_name FROM information_schema.tables
           WHERE table_schema=current_schema() AND table_name LIKE 'football_fixture_result%'""",
    )
    assert before == []
    preserved_queries = {
        "official_matches": "SELECT * FROM official_matches ORDER BY id",
        "official_results": "SELECT * FROM official_results ORDER BY id",
        "football_pool_issues": "SELECT * FROM football_pool_issues ORDER BY id",
        "football_pool_issue_matches": "SELECT * FROM football_pool_issue_matches ORDER BY id",
        "football_fixtures": "SELECT * FROM football_fixtures ORDER BY id",
        "football_fixture_source_links": "SELECT * FROM football_fixture_source_links ORDER BY source_name,id_system,source_match_id",
        "football_pool_fixture_revisions": "SELECT * FROM football_pool_fixture_revisions ORDER BY id",
    }
    preserved_rows = {name: _rows(conn, query) for name, query in preserved_queries.items()}

    with conn.cursor() as cur:
        cur.execute(MIGRATION.read_text())
        cur.execute("SHOW lock_timeout")
        assert cur.fetchone()[0] == "2s"
        cur.execute("SHOW statement_timeout")
        assert cur.fetchone()[0] == "30s"
        assert _rows(conn, "SELECT to_regclass('football_fixture_result_facts')") == [
            ("football_fixture_result_facts",)
        ]
        assert _rows(conn, "SELECT count(*) FROM football_fixture_result_facts") == [(0,)]
        for name, query in preserved_queries.items():
            assert _rows(conn, query) == preserved_rows[name]
    conn.rollback()

    assert _rows(conn, "SELECT to_regclass('football_fixture_result_facts')") == [(None,)]
    assert (
        _rows(
            conn,
            """SELECT table_name FROM information_schema.tables
           WHERE table_schema=current_schema() AND table_name LIKE 'football_fixture_result%'""",
        )
        == []
    )
    for name, query in preserved_queries.items():
        assert _rows(conn, query) == preserved_rows[name]
