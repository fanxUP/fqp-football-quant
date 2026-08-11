from pathlib import Path

SQL = Path("sql/96_news_feature_snapshots.sql").read_text()
ROLLBACK = Path("sql/down/96_news_feature_snapshots.down.sql").read_text()


def test_news_snapshot_schema_is_immutable_and_versioned() -> None:
    assert "CREATE TABLE IF NOT EXISTS match_news_snapshots" in SQL
    assert "CREATE TABLE IF NOT EXISTS match_news_features" in SQL
    assert "UNIQUE (match_id, snapshot_label, feature_version)" in SQL
    assert "snapshot_cutoff TIMESTAMPTZ NOT NULL" in SQL
    assert "event_payload JSONB NOT NULL" in SQL
    assert "checksum CHAR(64) NOT NULL" in SQL
    assert "verified_at TIMESTAMPTZ" in SQL


def test_news_snapshot_rollback_removes_only_p3_objects() -> None:
    assert "DROP TABLE IF EXISTS match_news_features" in ROLLBACK
    assert "DROP TABLE IF EXISTS match_news_snapshots" in ROLLBACK
    assert "DROP TABLE IF EXISTS news_events" not in ROLLBACK
