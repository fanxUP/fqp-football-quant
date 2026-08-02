from pathlib import Path


def test_agent_ticket_multiple_repair_splits_legacy_tickets_without_changing_totals():
    migration = Path("sql/69_split_agent_ticket_multiples.sql")

    assert migration.exists()
    source = migration.read_text(encoding="utf-8")
    assert "multiple > 50" in source
    assert "simulation_ticket_items" in source
    assert "ticket_settlements" in source
    assert "suggested_stake" in source
    assert "ledger_ticket_no" not in source
