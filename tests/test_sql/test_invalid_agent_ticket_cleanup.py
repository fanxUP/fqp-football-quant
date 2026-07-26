from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/54_purge_invalid_agent_tickets.sql")


def test_invalid_agent_tickets_are_removed_with_dependent_rows():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "ticket_status IN ('invalid', 'invalidated')" in source
    assert "DELETE FROM evidence_chain_audit_logs" in source
    assert "DELETE FROM ticket_settlements" in source
    assert "DELETE FROM simulation_ticket_items" in source
    assert "DELETE FROM simulation_tickets" in source
    assert "UPDATE real_tickets" in source
    assert "related_simulation_ticket_id = NULL" in source
