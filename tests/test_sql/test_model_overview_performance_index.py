from pathlib import Path


def test_model_overview_has_a_valid_prediction_covering_index():
    migration = Path("sql/100_model_overview_performance.sql")

    assert migration.exists()
    sql = " ".join(migration.read_text(encoding="utf-8").split())
    assert "idx_predictions_model_valid_match_covering" in sql
    assert "model_version_id, match_id, predict_time DESC" in sql
    assert "WHERE validation_status = 'valid'" in sql
