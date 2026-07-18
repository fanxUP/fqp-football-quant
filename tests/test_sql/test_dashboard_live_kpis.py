from pathlib import Path


def test_dashboard_kpi_migration_uses_live_agent_ticket_contract():
    migration = Path("sql/42_rebuild_dashboard_live_ticket_kpis.sql").read_text()

    assert "simulation_tickets" in migration
    assert "simulation_ticket_items" in migration
    assert "ai_settled_stake_today" in migration
    assert "agent_pending_stats" in migration
    assert "ticket_status NOT IN ('settled', 'cancelled')" in migration
    assert "AT TIME ZONE 'Asia/Shanghai'" in migration
    assert "SUM(st.total_cost)" not in migration
    assert "SUM(st.bet_count)" not in migration
    assert "ts.is_won IS NULL" not in migration
