from datetime import datetime
from unittest.mock import MagicMock

from scripts.jobs import run_recommendation_candidate as recommendation
from scripts.jobs.run_recommendation_candidate import (
    _buy_ticket,
    _no_candidate_note,
    _prediction_sp_value,
    _ticket_generation_note,
)


def test_prediction_sp_value_does_not_treat_kickoff_as_sp():
    row = tuple(range(15)) + (datetime(2026, 7, 11, 3), 1.46, "market_baseline")

    assert _prediction_sp_value(row) == 1.46


def test_agent_purchase_uses_agent_ticket_ledger(monkeypatch):
    stored = {}

    def fake_store(conn, ticket, items):
        stored.update({"conn": conn, "ticket": ticket, "items": items})
        return 91

    monkeypatch.setattr(recommendation, "store_simulation_ticket", fake_store)
    conn = object()
    ticket = {"suggested_stake": 20, "strategy_pool": "agent_value"}
    items = [{"match_id": 7}]

    assert _buy_ticket(conn, ticket, items) == 91
    assert stored == {"conn": conn, "ticket": ticket, "items": items}


def test_agent_purchase_rolls_back_failed_ticket_write(monkeypatch):
    conn = MagicMock()
    monkeypatch.setattr(
        recommendation,
        "store_simulation_ticket",
        lambda conn, ticket, items: (_ for _ in ()).throw(RuntimeError("write failed")),
    )

    assert _buy_ticket(conn, {"suggested_stake": 20}, [{"match_id": 7}]) is None
    conn.rollback.assert_called_once()


def test_no_candidate_note_exposes_data_quality_rejections():
    note = _no_candidate_note(
        total_predictions=78,
        rejection_counts={"data_quality": 78},
        minimum_quality=50,
    )

    assert note == "数据完整度不足：78 条预测未达到 50 分门槛，今日不投注"


def test_ticket_generation_note_exposes_pool_risk_rejections():
    assert _ticket_generation_note(tickets_created=0, candidate_count=3) == (
        "发现 3 个正 EV 候选，但均未通过资金池风险与置信度门槛，今日不投注"
    )
