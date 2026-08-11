from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/95_news_intelligence_events.sql")
ROLLBACK = Path("sql/down/95_news_intelligence_events.down.sql")


def test_news_event_schema_separates_events_entities_evidence_and_reviews() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    for table in (
        "news_events",
        "news_event_entities",
        "news_event_evidence",
        "news_event_reviews",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source

    assert "event_fingerprint" in source
    assert "first_available_at" in source
    assert "verification_status" in source
    assert "REFERENCES news_articles_raw(id)" in source
    assert "REFERENCES official_matches(id)" in source
    assert "CHECK (confidence_score >= 0 AND confidence_score <= 1)" in source


def test_news_event_schema_has_reverse_order_rollback() -> None:
    source = ROLLBACK.read_text(encoding="utf-8")

    assert source.index("DROP TABLE IF EXISTS news_event_reviews") < source.index(
        "DROP TABLE IF EXISTS news_events"
    )
