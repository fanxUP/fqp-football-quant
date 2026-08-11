from __future__ import annotations

from pathlib import Path

MIGRATION = Path("sql/100_news_source_policies.sql")
ROLLBACK = Path("sql/down/100_news_source_policies.down.sql")


def test_news_source_policy_schema_has_domain_level_type_and_switch() -> None:
    source = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS news_source_policies" in source
    assert "publisher_domain" in source
    assert "source_level" in source
    assert "source_type" in source
    assert "enabled" in source
    assert "thecfa.cn" in source
    assert "uefa.com" in source
    assert "sports.sina.com.cn" in source


def test_news_source_policy_schema_can_be_rolled_back() -> None:
    assert "DROP TABLE IF EXISTS news_source_policies" in ROLLBACK.read_text(encoding="utf-8")
