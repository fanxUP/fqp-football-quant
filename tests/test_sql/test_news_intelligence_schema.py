from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/94_news_intelligence_foundation.sql")
ROLLBACK = Path("sql/down/94_news_intelligence_foundation.down.sql")


def test_news_intelligence_foundation_is_append_only_and_source_aware() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "news_sources",
        "news_articles_raw",
        "news_article_matches",
        "news_ingestion_runs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source

    assert "CHECK (source_level IN ('S', 'A', 'B', 'C', 'D'))" in source
    assert "published_at" in source
    assert "observed_at" in source
    assert "captured_at" in source
    assert "available_at" in source
    assert "UNIQUE (provider_code, external_id)" in source
    assert "UNIQUE (canonical_url)" in source
    assert "REFERENCES official_matches(id)" in source


def test_news_intelligence_foundation_has_reverse_order_rollback() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert source.index("DROP TABLE IF EXISTS news_ingestion_runs") < source.index(
        "DROP TABLE IF EXISTS news_sources"
    )
    assert "DROP TABLE IF EXISTS news_article_matches" in source
    assert "DROP TABLE IF EXISTS news_articles_raw" in source
