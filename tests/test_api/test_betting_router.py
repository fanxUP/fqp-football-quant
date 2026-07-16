"""Unified betting router contract tests."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi import HTTPException

from apps.backend.src.routers import betting


def test_map_simulator_ticket_uses_my_simulation_contract():
    ticket = betting._map_simulator_ticket(
        {
            "id": 7,
            "play_type": "spf",
            "pass_type": "2x1",
            "multiple": 3,
            "total_cost": 12,
            "bet_count": 2,
            "max_prize": 88.5,
            "match_count": 2,
            "status": "pending",
            "created_at": "2026-07-07T10:00:00",
            "item_count": 2,
            "ledger_ticket_no": "20260707001",
        }
    )

    assert ticket["ticketUid"] == "simulator:7"
    assert ticket["owner"] == "me"
    assert ticket["kind"] == "simulation"
    assert ticket["date"] == "2026-07-07"
    assert ticket["ticketNumber"] == "20260707001"
    assert ticket["stake"] == 12.0
    assert ticket["route"] == "/simulator/history/7"


def test_map_real_ticket_can_belong_to_agent_column():
    ticket = betting._map_real_ticket(
        {
            "id": 12,
            "source_type": "agent",
            "ocr_status": "recognized",
            "settlement_status": "settled",
            "purchase_time": "2026-07-06T20:00:00",
            "created_at": "2026-07-06T21:00:00",
            "total_amount": 24,
            "theoretical_max_prize": 180,
            "multiple": 2,
            "pass_type": "3x1",
            "item_count": 3,
            "confirm_status": "confirmed",
            "related_simulation_ticket_id": 99,
            "ledger_ticket_no": "20260706001",
        }
    )

    assert ticket["ticketUid"] == "real:12"
    assert ticket["owner"] == "agent"
    assert ticket["kind"] == "real"
    assert ticket["source"] == "ocr"
    assert ticket["status"] == "settled"
    assert ticket["ticketNumber"] == "20260706001"
    assert ticket["linkedSimulationId"] == 99


def test_map_agent_ticket_uses_agent_recommendation_source():
    row = (
        31,
        50,
        0.1234,
        "agent_value",
        "medium",
        "pending",
        datetime(2026, 7, 7, 16, 0, 0),
        "single",
        "single",
        1,
        1,
        1,
        "20260707002",
    )

    ticket = betting._map_agent_ticket(row)

    assert ticket["ticketUid"] == "agent:31"
    assert ticket["owner"] == "agent"
    assert ticket["source"] == "agent_recommendation"
    assert ticket["date"] == "2026-07-07"
    assert ticket["ticketNumber"] == "20260707002"
    assert ticket["expectedValue"] == 0.1234


def test_create_real_betting_ticket_maps_agent_source(monkeypatch):
    created: dict[str, object] = {}
    inserted_items: list[dict] = []

    def fake_create_real_ticket(conn, ticket):
        created.update(ticket)
        return 88

    def fake_create_items(conn, ticket_id, items):
        inserted_items.extend(items)
        return [1]

    monkeypatch.setattr(betting, "create_real_ticket", fake_create_real_ticket)
    monkeypatch.setattr(betting, "create_real_ticket_items_batch", fake_create_items)

    req = betting.CreateBettingTicketRequest(
        source="real-agent",
        play_type="spf",
        pass_type="single",
        multiple=2,
        items=[
            betting.BettingTicketItemRequest(
                match_id=1001,
                play_type="spf",
                option_code="3",
                option_name="胜",
                sp_value=2.5,
            )
        ],
    )

    result = betting._create_real_betting_ticket(object(), req)

    assert created["source_type"] == "agent"
    assert created["total_amount"] == 4
    assert created["theoretical_max_prize"] == 10
    assert result["ticketUid"] == "real:88"
    assert result["owner"] == "agent"
    assert inserted_items[0]["match_id"] == 1001


def test_create_real_betting_ticket_attaches_ocr_confirmation(monkeypatch):
    created: dict[str, object] = {}

    def fake_create_real_ticket(conn, ticket):
        created.update(ticket)
        return 89

    monkeypatch.setattr(betting, "create_real_ticket", fake_create_real_ticket)
    monkeypatch.setattr(betting, "create_real_ticket_items_batch", lambda conn, ticket_id, items: [1])

    req = betting.CreateBettingTicketRequest(
        source="real-user",
        play_type="spf",
        pass_type="single",
        multiple=1,
        ticket_no="T20260707001",
        store_code="31010101",
        ticket_image_url="/uploads/tickets/ticket.jpg",
        ocr_status="recognized",
        items=[
            betting.BettingTicketItemRequest(
                match_id=1002,
                play_type="spf",
                option_code="1",
                option_name="平",
                sp_value=3.0,
            )
        ],
    )

    result = betting._create_real_betting_ticket(object(), req)

    assert created["ticket_image_url"] == "/uploads/tickets/ticket.jpg"
    assert created["ticket_no"] == "T20260707001"
    assert created["store_code"] == "31010101"
    assert created["ocr_status"] == "recognized"
    assert result["source"] == "ocr"


def test_multi_pass_ticket_rejects_combined_cost_over_twenty_thousand():
    items = [
        {
            "match_id": match_id,
            "play_type": "spf",
            "option_code": str(option),
            "option_name": str(option),
            "sp_value": 2.0,
            "is_single_allowed": True,
            "is_pass_allowed": True,
        }
        for match_id in range(1, 5)
        for option in range(5)
    ]

    with pytest.raises(HTTPException, match="单票金额不得超过20000元"):
        betting._calculate_multi_pass_ticket(items, "3x1,4x1", multiple=10)


def test_apply_settlements_updates_ticket_financials():
    tickets = [
        {
            "ticketUid": "simulator:7",
            "owner": "me",
            "kind": "simulation",
            "source": "manual",
            "status": "pending",
            "date": "2026-07-07",
            "stake": 12.0,
            "settledAmount": None,
            "profitLoss": None,
            "roi": None,
        },
        {
            "ticketUid": "agent:31",
            "owner": "agent",
            "kind": "simulation",
            "source": "agent_recommendation",
            "status": "pending",
            "date": "2026-07-07",
            "stake": 50.0,
            "settledAmount": None,
            "profitLoss": None,
            "roi": None,
        },
        {
            "ticketUid": "real:12",
            "owner": "me",
            "kind": "real",
            "source": "manual",
            "status": "pending",
            "date": "2026-07-07",
            "stake": 20.0,
            "settledAmount": None,
            "profitLoss": None,
            "roi": None,
        },
    ]

    betting._apply_settlements(
        tickets,
        [
            ("simulator", 7, datetime(2026, 7, 7, 22, 0, 0), True, 12, 30, 0, 30, 18, 1.5),
            ("simulation", 31, datetime(2026, 7, 7, 22, 1, 0), False, 50, 0, 0, 0, -50, -1),
            ("real", 12, datetime(2026, 7, 7, 22, 2, 0), True, 20, 48, 0, 48, 28, 1.4),
        ],
    )

    assert tickets[0]["status"] == "settled"
    assert tickets[0]["settledAmount"] == 30.0
    assert tickets[0]["profitLoss"] == 18.0
    assert tickets[0]["roi"] == 1.5
    assert tickets[0]["settledAt"] == "2026-07-07T22:00:00"
    assert tickets[1]["status"] == "settled"
    assert tickets[1]["settledAmount"] == 0.0
    assert tickets[1]["profitLoss"] == -50.0
    assert tickets[2]["status"] == "settled"
    assert tickets[2]["settledAmount"] == 48.0
    assert tickets[2]["profitLoss"] == 28.0


def test_attach_ticket_items_adds_compact_match_summaries():
    class Cursor:
        def __init__(self):
            self.rows: list[tuple] = []

        def execute(self, sql, params):
            if "simulator_ticket_items" in sql:
                self.rows = [
                    (7, 1001, "周二001", "阿森纳", "切尔西", "spf", "3", "胜", 1.8),
                ]
            elif "real_ticket_items" in sql:
                self.rows = [
                    (12, 1002, "周二002", "米兰", "国米", "rqspf", "0", "让负", 2.1),
                ]
            elif "simulation_ticket_items" in sql:
                self.rows = [
                    (31, 1003, "周二003", "巴黎", "里昂", "bf", "2:1", "2:1", 7.5),
                ]
            else:
                self.rows = []

        def fetchall(self):
            return self.rows

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class Conn:
        def cursor(self):
            return Cursor()

    tickets = [
        {"ticketUid": "simulator:7"},
        {"ticketUid": "real:12"},
        {"ticketUid": "agent:31"},
    ]

    betting._attach_ticket_items(Conn(), tickets)

    assert tickets[0]["items"][0] == {
        "matchId": 1001,
        "matchCode": "周二001",
        "homeTeam": "阿森纳",
        "awayTeam": "切尔西",
        "playType": "spf",
        "optionCode": "3",
        "optionName": "胜",
        "spValue": 1.8,
        "oddsSource": "official",
    }
    assert tickets[1]["items"][0]["homeTeam"] == "米兰"
    assert tickets[2]["items"][0]["matchCode"] == "周二003"


def test_build_betting_results_splits_me_and_agent():
    result = betting._build_betting_results(
        [
            {
                "ticketUid": "simulator:1",
                "owner": "me",
                "kind": "simulation",
                "source": "manual",
                "status": "settled",
                "date": "2026-07-07",
                "stake": 10,
                "settledAmount": 25,
                "profitLoss": 15,
                "roi": 1.5,
            },
            {
                "ticketUid": "real:2",
                "owner": "agent",
                "kind": "real",
                "source": "ocr",
                "status": "pending",
                "date": "2026-07-07",
                "stake": 20,
                "settledAmount": None,
                "profitLoss": None,
                "roi": None,
            },
            {
                "ticketUid": "agent:3",
                "owner": "agent",
                "kind": "simulation",
                "source": "agent_recommendation",
                "status": "settled",
                "date": "2026-07-08",
                "stake": 30,
                "settledAmount": 0,
                "profitLoss": -30,
                "roi": -1,
            },
        ]
    )

    assert result["owners"]["me"]["stake"] == 10
    assert result["owners"]["me"]["profitLoss"] == 15
    assert result["owners"]["me"]["roi"] == 1.5
    assert result["owners"]["agent"]["stake"] == 30
    assert result["owners"]["agent"]["pending"] == 1
    assert result["owners"]["agent"]["profitLoss"] == -30
    assert result["leader"] == "me"
    assert result["trend"][-1]["agentCumulativeProfitLoss"] == -30


def test_build_betting_results_fills_every_day_from_first_item_ticket():
    result = betting._build_betting_results(
        [
            {
                "ticketUid": "agent:1",
                "owner": "agent",
                "kind": "simulation",
                "source": "agent_recommendation",
                "status": "pending",
                "date": "2026-07-04",
                "itemCount": 2,
                "stake": 20,
            },
            {
                "ticketUid": "agent:2",
                "owner": "agent",
                "kind": "simulation",
                "source": "agent_recommendation",
                "status": "settled",
                "date": "2026-07-05",
                "settledAt": "2026-07-06T12:00:00",
                "itemCount": 1,
                "stake": 10,
                "settledAmount": 25,
                "profitLoss": 15,
                "roi": 1.5,
            },
        ],
        trend_start_date=date(2026, 7, 4),
        today=date(2026, 7, 8),
    )

    assert [point["date"] for point in result["trend"]] == [
        "2026-07-04",
        "2026-07-05",
        "2026-07-06",
        "2026-07-07",
        "2026-07-08",
    ]
    assert [point["agentDailyProfitLoss"] for point in result["trend"]] == [
        0,
        0,
        15,
        0,
        0,
    ]
    assert [point["agentCumulativeProfitLoss"] for point in result["trend"]] == [
        0,
        0,
        15,
        15,
        15,
    ]


def test_build_betting_results_ignores_empty_ticket_as_trend_start():
    result = betting._build_betting_results(
        [
            {
                "ticketUid": "agent:1",
                "owner": "agent",
                "kind": "simulation",
                "source": "agent_recommendation",
                "status": "pending",
                "date": "2026-07-01",
                "itemCount": 0,
                "stake": 20,
            }
        ],
        today=date(2026, 7, 8),
    )

    assert result["trend"] == []


def test_build_betting_results_excludes_settlements_before_ticket_start():
    result = betting._build_betting_results(
        [
            {
                "ticketUid": "agent:legacy",
                "owner": "agent",
                "kind": "simulation",
                "source": "agent_recommendation",
                "status": "settled",
                "date": "2026-07-01",
                "settledAt": "2026-07-02T12:00:00",
                "stake": 20,
                "settledAmount": 0,
                "profitLoss": -20,
            }
        ],
        trend_start_date=date(2026, 7, 4),
        today=date(2026, 7, 5),
    )

    assert [point["date"] for point in result["trend"]] == [
        "2026-07-04",
        "2026-07-05",
    ]
    assert result["trend"][-1]["agentCumulativeProfitLoss"] == 0


def test_fetch_settled_betting_tickets_maps_all_historical_sources():
    class Cursor:
        def execute(self, sql):
            self.sql = sql

        def fetchall(self):
            return [
                (
                    "simulation",
                    39,
                    datetime(2026, 7, 4, 10, 11, 45),
                    False,
                    20,
                    0,
                    -20,
                    -1,
                    None,
                    None,
                ),
                (
                    "real",
                    12,
                    datetime(2026, 7, 7, 22, 2, 0),
                    True,
                    20,
                    48,
                    28,
                    1.4,
                    "agent",
                    "recognized",
                ),
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class Conn:
        def cursor(self):
            return Cursor()

    tickets = betting._fetch_settled_betting_tickets(Conn())

    assert tickets[0]["ticketUid"] == "agent:39"
    assert tickets[0]["owner"] == "agent"
    assert tickets[0]["source"] == "agent_recommendation"
    assert tickets[0]["profitLoss"] == -20.0
    assert tickets[1]["ticketUid"] == "real:12"
    assert tickets[1]["owner"] == "agent"
    assert tickets[1]["source"] == "ocr"


def test_result_ticket_merge_replaces_current_settled_rows_with_full_history():
    current = [
        {"ticketUid": "agent:52", "status": "pending"},
        {"ticketUid": "agent:39", "status": "settled", "profitLoss": -20},
    ]
    settled = [
        {"ticketUid": "agent:39", "status": "settled", "profitLoss": -20},
        {"ticketUid": "agent:40", "status": "settled", "profitLoss": -20},
    ]

    merged = betting._merge_result_tickets(current, settled)

    assert [ticket["ticketUid"] for ticket in merged] == ["agent:52", "agent:39", "agent:40"]
