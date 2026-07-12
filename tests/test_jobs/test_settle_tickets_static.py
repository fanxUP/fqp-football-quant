"""Static regression tests for ticket settlement safety-critical branches."""

from __future__ import annotations

from pathlib import Path

SETTLE_TICKETS = Path("scripts/jobs/settle_tickets.py")


def _section(source: str, start: str, end: str) -> str:
    start_index = source.index(start)
    end_index = source.index(end, start_index)
    return source[start_index:end_index]


def test_simulator_prize_credit_uses_simulator_win_flag():
    source = SETTLE_TICKETS.read_text(encoding="utf-8")
    simulator_section = _section(source, "# 3. Settle simulator tickets", "# 4. Settle real tickets")

    assert "if ticket_won and net_prize > 0:" in simulator_section
    assert "calculate_winning_prize(detail, pass_type, multiple)" in simulator_section
    assert "if ticket_all_won and net_prize > 0:" not in simulator_section


def test_real_ticket_prize_credit_uses_real_win_flag():
    source = SETTLE_TICKETS.read_text(encoding="utf-8")
    real_section = _section(source, "# 4. Settle real tickets", "return {")

    assert "if real_all_won and net_prize > 0:" in real_section
    assert "if all_won and net_prize > 0:" not in real_section
