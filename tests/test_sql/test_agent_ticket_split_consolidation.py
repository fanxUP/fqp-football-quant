from pathlib import Path


def test_equivalent_agent_ticket_fragments_are_consolidated_into_50x_tickets():
    migration = Path("sql/70_consolidate_agent_ticket_splits.sql")

    assert migration.exists()
    source = migration.read_text(encoding="utf-8")
    assert "SUM(multiple) % 50 = 0" in source
    assert "simulation_ticket_items" in source
    assert "ticket_settlements" in source
    assert "multiple = 50" in source
