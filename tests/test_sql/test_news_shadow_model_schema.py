from pathlib import Path

ROLLBACK = Path("sql/down/97_news_shadow_model.down.sql").read_text()
SQL = Path("sql/97_news_shadow_model.sql").read_text()


def test_news_shadow_schema_keeps_baseline_and_adjusted_probabilities() -> None:
    assert "CREATE TABLE IF NOT EXISTS news_shadow_predictions" in SQL
    assert "baseline_probabilities JSONB NOT NULL" in SQL
    assert "shadow_probabilities JSONB NOT NULL" in SQL
    assert "baseline_model_version_id BIGINT NOT NULL" in SQL
    assert "UNIQUE (match_id, snapshot_id, baseline_model_version_id, shadow_version)" in SQL
    assert "CREATE TABLE IF NOT EXISTS news_shadow_evaluations" in SQL
    assert "baseline_brier" in SQL
    assert "shadow_brier" in SQL


def test_news_shadow_rollback_does_not_touch_formal_predictions() -> None:
    assert "DROP TABLE IF EXISTS news_shadow_predictions" in ROLLBACK
    assert "model_predictions" not in ROLLBACK
