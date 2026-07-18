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
    simulator_section = _section(
        source, "# 3. Settle simulator tickets", "# 4. Settle real tickets"
    )

    assert "if ticket_won and net_prize > 0:" in simulator_section
    assert "calculate_winning_prize(detail, pass_type, multiple)" in simulator_section
    assert "if ticket_all_won and net_prize > 0:" not in simulator_section


def test_agent_ticket_uses_combination_prize_calculator():
    source = SETTLE_TICKETS.read_text(encoding="utf-8")
    agent_section = _section(
        source, "# 2. Settle simulation tickets", "# 3. Settle simulator tickets"
    )

    assert "_calculate_agent_prize(" in agent_section
    assert "if agent_ticket_won and net_prize > 0:" in agent_section
    assert "stake * product_sp" not in agent_section


def test_real_ticket_prize_credit_uses_real_win_flag():
    source = SETTLE_TICKETS.read_text(encoding="utf-8")
    real_section = _section(source, "# 4. Settle real tickets", "return {")

    assert "calculate_winning_prize(real_detail, pass_type, multiple)" in real_section
    assert "if real_ticket_won and net_prize > 0:" in real_section
    assert "ai_option == result_map[ai_match_id]" not in real_section
    assert "if all_won and net_prize > 0:" not in real_section


def test_confirmed_void_results_are_not_filtered_out_before_settlement():
    source = SETTLE_TICKETS.read_text(encoding="utf-8")
    result_query = _section(source, "# 1. Find confirmed results", "# Build result lookup")

    assert "r.raw_json" in result_query
    assert "r.spf_result IS NOT NULL" not in result_query
    assert "_is_void_result" in source
