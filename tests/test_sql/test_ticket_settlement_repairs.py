from pathlib import Path


MIGRATION = Path("sql/40_ticket_settlement_repairs.sql")


def test_orphan_agent_tickets_are_cancelled_by_migration():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "UPDATE simulation_tickets" in source
    assert "SET ticket_status = 'cancelled'" in source
    assert "NOT EXISTS" in source
    assert "simulation_ticket_items" in source
