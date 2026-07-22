from datetime import date, datetime
from unittest.mock import MagicMock

from scripts.daily_decision_storage import (
    list_agent_daily_decisions,
    upsert_agent_daily_decision,
)


def test_upsert_daily_decision_records_abstention_reason():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value

    upsert_agent_daily_decision(
        conn,
        decision_date=date(2026, 7, 14),
        status="abstained",
        total_stake=0,
        reason="数据完整度不足，今日不投注",
    )

    sql, params = cur.execute.call_args.args
    assert "ON CONFLICT (plan_date) DO UPDATE" in sql
    assert params["status"] == "abstained"
    assert params["unused_budget"] == 500.0
    assert params["reason"] == "数据完整度不足，今日不投注"
    conn.commit.assert_called_once()


def test_list_daily_decisions_maps_decision_contract():
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        (
            date(2026, 7, 14),
            500,
            20,
            480,
            "purchased",
            "已创建 1 张 Agent 虚拟票",
            datetime(2026, 7, 14, 16, 0),
            "formal",
        )
    ]

    rows = list_agent_daily_decisions(conn, limit=14)

    assert rows == [
        {
            "decisionDate": "2026-07-14",
            "status": "purchased",
            "totalBudget": 500.0,
            "totalStake": 20.0,
            "unusedBudget": 480.0,
            "reason": "已创建 1 张 Agent 虚拟票",
            "updatedAt": "2026-07-14T16:00:00",
            "decisionType": "formal",
        }
    ]

    sql, _ = cur.execute.call_args.args
    assert "ticket_type = 'training_observation'" in sql
    assert "COALESCE(st.strategy_pool, '') LIKE '%%observation%%'" in sql
    assert "decision_type" in sql


def test_list_daily_decisions_identifies_observation_ticket() -> None:
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchall.return_value = [
        (
            date(2026, 7, 22),
            500,
            2,
            498,
            "purchased",
            "已生成高风险虚拟观察票",
            datetime(2026, 7, 22, 16, 0),
            "observation",
        )
    ]

    rows = list_agent_daily_decisions(conn, limit=14)

    assert rows[0]["decisionType"] == "observation"
