from pathlib import Path

ROLLBACK = Path("sql/down/98_news_release_control.down.sql").read_text()
SQL = Path("sql/98_news_release_control.sql").read_text()


def test_release_schema_defaults_to_shadow_and_keeps_history() -> None:
    assert "CREATE TABLE IF NOT EXISTS news_feature_release_settings" in SQL
    assert "mode VARCHAR(16) NOT NULL DEFAULT 'shadow'" in SQL
    assert "CREATE TABLE IF NOT EXISTS news_feature_release_history" in SQL
    assert "approved_shadow_version" in SQL
    assert "INSERT INTO news_feature_release_settings (id, mode)" in SQL


def test_release_rollback_does_not_delete_news_evidence() -> None:
    assert "DROP TABLE IF EXISTS news_feature_release_settings" in ROLLBACK
    assert "news_articles_raw" not in ROLLBACK
    assert "news_events" not in ROLLBACK
