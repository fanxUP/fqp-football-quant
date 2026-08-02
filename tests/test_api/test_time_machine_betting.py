"""Contracts for historical time-machine ticket entry."""

from __future__ import annotations

from datetime import date, datetime

from apps.backend.src.services.time_machine_betting import build_time_machine_matches
from apps.backend.src.routers import time_machine


def test_time_machine_keeps_the_last_official_open_odds_before_sales_stop():
    matches = [
        (101, "周日001", "挪超", "布兰", "瓦勒伦加", datetime(2026, 7, 26, 22), datetime(2026, 7, 26, 21, 30), {}),
    ]
    odds = [
        (101, 7001, datetime(2026, 7, 26, 21, 20), "spf", "3", "主胜", 1.86, None, True),
        # This later update was captured after the official selling stop and must not leak in.
        (101, 7002, datetime(2026, 7, 26, 21, 35), "spf", "3", "主胜", 1.74, None, True),
    ]

    result = build_time_machine_matches(matches, odds)

    option = result[0]["odds"]["spf"]["options"][0]
    assert option["sp_value"] == 1.86
    assert option["odds_snapshot_id"] == 7001
    assert option["snapshot_time"] == "2026-07-26T21:20:00"


def test_time_machine_ticket_persists_historical_purchase_date_and_server_resolved_odds(monkeypatch):
    stored: dict[str, object] = {}
    stored_items: list[dict] = []

    class DbContext:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(time_machine, "get_db", lambda: DbContext())
    monkeypatch.setattr(
        time_machine,
        "_resolve_selections",
        lambda _conn, _request: [{
            "match_id": 101, "official_match_code": "周日001", "play_type": "spf",
            "option_code": "3", "option_name": "主胜", "sp_value": 1.86,
            "odds_snapshot_id": 7001, "odds_snapshot_time": datetime(2026, 7, 26, 21, 20),
            "odds_source": "official_pre_close", "is_single_allowed": True, "is_pass_allowed": True,
        }],
    )
    monkeypatch.setattr(time_machine, "create_real_ticket", lambda _conn, ticket: stored.update(ticket) or 77)
    monkeypatch.setattr(time_machine, "create_real_ticket_items_batch", lambda _conn, _ticket_id, items: stored_items.extend(items) or [1])

    result = time_machine.create_time_machine_ticket(
        time_machine.CreateTimeMachineTicketRequest(
            business_date=date(2026, 7, 26), pass_type="single", multiple=1,
            selections=[{"match_id": 101, "play_type": "spf", "option_code": "3"}],
        )
    )

    assert result["ticketUid"] == "real:77"
    assert stored["purchase_time"] == "2026-07-26"
    assert stored["source_type"] == "time_machine_manual"
    assert stored_items[0]["sp_value"] == 1.86
    assert stored_items[0]["odds_snapshot_id"] == 7001
