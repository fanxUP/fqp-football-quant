from pathlib import Path


def test_live_read_indexes_cover_betting_odds_and_evaluation_history():
    migration = Path("sql/56_live_read_performance_indexes.sql")

    assert migration.exists()
    sql = " ".join(migration.read_text(encoding="utf-8").split())
    assert "idx_odds_open_latest_covering" in sql
    assert "WHERE is_open = true" in sql
    assert "INCLUDE (option_name, sp_value, handicap, is_single_allowed)" in sql
    assert "idx_predictions_independent_match_latest" in sql
    assert "uncertainty_reason ->> 'model_independent'" in sql
    assert "validation_status = 'valid'" in sql
