"""Complete real-ticket writes must survive failures without partial purchases."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql

from apps.backend.src.app import create_app
from apps.backend.src.routers import betting, tickets, time_machine
from scripts.ticket_settlement import settle_ticket_atomically


@pytest.fixture
def ticket_database(monkeypatch):
    dsn = os.environ.get("FQP_AUDIT_TEST_DATABASE_URL", "")
    if not dsn:
        pytest.skip("set FQP_AUDIT_TEST_DATABASE_URL to a disposable local audit database")
    parsed = urlparse(dsn)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    assert parsed.path.lstrip("/").startswith("fqp_audit_test_")
    conn = psycopg2.connect(dsn, options="-c statement_timeout=5000 -c lock_timeout=1000")
    schema = f"ticket_{uuid4().hex}"
    root = Path(__file__).resolve().parents[2]
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            for table in ("official_matches", "official_odds_snapshots", "model_predictions"):
                cur.execute(
                    sql.SQL("CREATE TABLE {} (id BIGINT PRIMARY KEY)").format(sql.Identifier(table))
                )
            cur.execute((root / "sql/04_recommendation_ticket_schema.sql").read_text())
            cur.execute((root / "sql/68_time_machine_ticket_evidence.sql").read_text())
            cur.execute("INSERT INTO official_matches VALUES (1), (2)")
            cur.execute("INSERT INTO official_odds_snapshots VALUES (101), (102)")
            cur.execute(
                "INSERT INTO bankroll_accounts (account_type, current_balance) VALUES ('real', 100)"
            )
        conn.autocommit = False

        @contextmanager
        def database():
            try:
                yield conn
            finally:
                conn.rollback()

        for module in (betting, tickets, time_machine):
            monkeypatch.setattr(module, "get_db", database)
        monkeypatch.setenv("FQP_AUTH_MODE", "none")
        with TestClient(create_app(), raise_server_exceptions=False) as client:
            yield conn, client
    finally:
        conn.rollback()
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.close()


def items():
    return [
        {
            "match_id": mid,
            "play_type": "spf",
            "option_code": "0",
            "option_name": "客胜",
            "sp_value": 2.5,
            "odds_snapshot_id": 100 + mid,
            "odds_source": "official_pre_close",
        }
        for mid in (1, 2)
    ]


def purchase(client, entry, selections, monkeypatch):
    if entry == "manual":
        return client.post(
            "/api/real-tickets", json={"ticket": {"total_amount": 4}, "items": selections}
        )
    if entry == "betting":
        return client.post(
            "/api/betting/tickets",
            json={
                "source": "real-user",
                "ocr_status": "recognized",
                "ticket_image_url": "/uploads/test.jpg",
                "pass_type": "single",
                "items": selections,
            },
        )
    # Selection resolution already has its own contract tests. Here exercise the
    # real historical route and storage with a controlled server-resolved vector.
    monkeypatch.setattr(time_machine, "_resolve_selections", lambda *_args: selections)
    return client.post(
        "/api/betting/time-machine/tickets",
        json={
            "business_date": "2020-01-01",
            "pass_type": "single",
            "selections": [{"match_id": 1, "play_type": "spf", "option_code": "0"}],
        },
    )


@pytest.mark.parametrize("entry", ["manual", "betting", "historical"])
@pytest.mark.parametrize("failure", ["missing_match", "second_item", "commit"])
def test_all_ticket_entries_roll_back_the_parent_and_items(
    ticket_database, monkeypatch, entry, failure
):
    conn, client = ticket_database
    selections = items()
    if failure == "missing_match":
        selections[1]["match_id"] = 999
    else:
        with conn.cursor() as cur:
            cur.execute("""CREATE FUNCTION reject_item() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN IF NEW.match_id=2 THEN RAISE EXCEPTION 'injected item failure'; END IF;
                RETURN NEW; END $$""")
            if failure == "commit":
                cur.execute("""CREATE CONSTRAINT TRIGGER reject_item_at_commit
                    AFTER INSERT ON real_ticket_items DEFERRABLE INITIALLY DEFERRED
                    FOR EACH ROW EXECUTE FUNCTION reject_item()""")
            else:
                cur.execute("""CREATE TRIGGER reject_second_item BEFORE INSERT ON real_ticket_items
                    FOR EACH ROW EXECUTE FUNCTION reject_item()""")
        conn.commit()

    response = purchase(client, entry, selections, monkeypatch)
    # Check persisted state before status so RED demonstrates the original
    # committed parent rather than merely a difference in error presentation.
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM real_tickets), (SELECT count(*) FROM real_ticket_items)"
        )
        assert cur.fetchone() == (0, 0)
    assert response.status_code == (422 if failure == "missing_match" else 500)


@pytest.mark.parametrize(
    ("ticket", "item_update"),
    [
        ({"purchase_time": "invalid-date"}, {}),
        ({}, {"sp_value": 1000000}),  # outside NUMERIC(10,4), on the second item
        ({}, {"option_name": "x" * 129}),
        ({}, {"odds_snapshot_id": 999}),
    ],
)
def test_database_field_errors_are_422_and_leave_no_partial_ticket(
    ticket_database, ticket, item_update
):
    conn, client = ticket_database
    selections = items()
    selections[1].update(item_update)
    response = client.post("/api/real-tickets", json={"ticket": ticket, "items": selections})
    assert response.status_code == 422
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (SELECT count(*) FROM real_tickets), (SELECT count(*) FROM real_ticket_items)"
        )
        assert cur.fetchone() == (0, 0)


def test_zero_values_are_saved_without_becoming_missing(ticket_database):
    conn, client = ticket_database
    response = client.post(
        "/api/real-tickets",
        json={
            "ticket": {"total_amount": 0, "theoretical_max_prize": 0},
            "items": [{"match_id": 1, "option_code": "0", "sp_value": 0}],
        },
    )
    assert response.status_code == 200
    with conn.cursor() as cur:
        cur.execute("""SELECT t.total_amount, t.theoretical_max_prize, i.option_code, i.sp_value
            FROM real_tickets t JOIN real_ticket_items i ON i.real_ticket_id=t.id""")
        assert cur.fetchone() == (0, 0, "0", 0)


@pytest.mark.parametrize("entry", ["manual", "betting", "historical"])
def test_saved_tickets_keep_evidence_and_settle_once_without_deduplicating_purchases(
    ticket_database, monkeypatch, entry
):
    conn, client = ticket_database
    first = purchase(client, entry, items(), monkeypatch)
    second = purchase(client, entry, items(), monkeypatch)
    assert first.status_code == second.status_code == 200
    body = first.json()
    ticket_id = body["ticket_id"] if entry == "manual" else body["legacyId"]
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM real_tickets")
        assert cur.fetchone()[0] == 2
        cur.execute("SELECT count(*) FROM real_ticket_items")
        assert cur.fetchone()[0] == 4
        cur.execute(
            "SELECT option_code, odds_snapshot_id, odds_source FROM real_ticket_items WHERE real_ticket_id=%s ORDER BY id",
            (ticket_id,),
        )
        rows = cur.fetchall()
        assert (
            rows == [("0", 101, "official_pre_close"), ("0", 102, "official_pre_close")]
            if entry != "betting"
            else rows == [("0", None, None), ("0", None, None)]
        )
    settlement = {
        "ticket_source": "real",
        "ticket_id": ticket_id,
        "is_won": True,
        "stake_amount": 4,
        "prize_amount": 10,
        "net_prize": 10,
        "profit_loss": 6,
    }
    assert settle_ticket_atomically(conn, settlement, remark="isolated regression") is True
    assert settle_ticket_atomically(conn, settlement, remark="retry") is False
    with conn.cursor() as cur:
        cur.execute("SELECT current_balance FROM bankroll_accounts WHERE account_type='real'")
        assert cur.fetchone()[0] == 110
        cur.execute("SELECT count(*) FROM ticket_settlements")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT count(*) FROM bankroll_transactions")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT settlement_status FROM real_tickets WHERE id=%s", (ticket_id,))
        assert cur.fetchone()[0] == "settled"
