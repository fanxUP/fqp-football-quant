from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/99_news_ai_screening.sql")
ROLLBACK = Path("sql/down/99_news_ai_screening.down.sql")


def test_news_ai_screening_schema_is_traceable_and_does_not_store_secrets() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS news_article_screenings" in source
    assert "CREATE TABLE IF NOT EXISTS news_model_invocations" in source
    assert "UNIQUE (article_id, match_id)" in source
    assert "prompt_sha256" in source
    assert "response_sha256" in source
    assert "api_key" not in source.lower()


def test_news_ai_screening_schema_has_reverse_order_rollback() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert source.index("DROP TABLE IF EXISTS news_model_invocations") < source.index(
        "DROP TABLE IF EXISTS news_article_screenings"
    )
