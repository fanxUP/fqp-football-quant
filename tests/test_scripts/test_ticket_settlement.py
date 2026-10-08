from unittest.mock import Mock

import pytest

from scripts import ticket_settlement as settlement


def connection(ticket=("pending", "confirmed"), existing=None):
    cur = Mock()
    cur.__enter__ = Mock(return_value=cur)
    cur.__exit__ = Mock(return_value=False)
    cur.fetchone.side_effect = [ticket, existing]
    cur.rowcount = 1
    conn = Mock()
    conn.cursor.return_value = cur
    return conn, cur


def ticket():
    return {"ticket_source": "real", "ticket_id": 7, "is_won": True, "net_prize": 12}


def test_settlement_commits_once_after_ledger_prize_and_status(monkeypatch):
    conn, cur = connection()
    ledger, prize = Mock(return_value=11), Mock(return_value=22)
    monkeypatch.setattr(settlement, "create_settlement", ledger)
    monkeypatch.setattr(settlement, "create_bankroll_transaction", prize)
    assert settlement.settle_ticket_atomically(conn, ticket(), remark="release check") is True
    assert ledger.call_args.kwargs == {"commit": False}
    assert prize.call_args.kwargs == {"commit": False}
    assert "UPDATE real_tickets" in cur.execute.call_args.args[0]
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()


def test_status_failure_rolls_back_prize_and_ledger(monkeypatch):
    conn, cur = connection()
    cur.rowcount = 0
    monkeypatch.setattr(settlement, "create_settlement", Mock(return_value=11))
    monkeypatch.setattr(settlement, "create_bankroll_transaction", Mock(return_value=22))
    with pytest.raises(RuntimeError, match="status update failed"):
        settlement.settle_ticket_atomically(conn, ticket(), remark="release check")
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_existing_ledger_never_recredits_prize(monkeypatch):
    conn, _ = connection(existing=(11,))
    prize = Mock()
    monkeypatch.setattr(settlement, "create_bankroll_transaction", prize)
    assert settlement.settle_ticket_atomically(conn, ticket(), remark="release check") is False
    prize.assert_not_called()
