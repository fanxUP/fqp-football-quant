from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/48_upset_intelligence_schema.sql")
ROLLBACK = Path("sql/down/48_upset_intelligence_schema.down.sql")


def test_upset_schema_contains_complete_versioned_research_chain():
    source = MIGRATION.read_text(encoding="utf-8")

    expected_tables = {
        "upset_rule_versions",
        "upset_events",
        "upset_market_signals",
        "upset_factor_evidence",
        "upset_reviews",
        "upset_report_metrics",
        "league_knowledge_profiles",
        "team_knowledge_profiles",
        "player_knowledge_profiles",
        "research_hypotheses",
        "hypothesis_validation_runs",
        "feature_promotion_audits",
    }
    for table in expected_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source

    assert "UNIQUE (match_id, detect_rule_version_id)" in source
    assert "available_at" in source
    assert "data_cutoff_at" in source
    assert "research_only" in source
    assert "CHECK (actual_outcome_probability > 0" in source


def test_upset_schema_has_reverse_order_rollback():
    source = ROLLBACK.read_text(encoding="utf-8")

    assert source.index("DROP TABLE IF EXISTS feature_promotion_audits") < source.index(
        "DROP TABLE IF EXISTS upset_rule_versions"
    )
    assert "DROP TABLE IF EXISTS upset_events" in source
