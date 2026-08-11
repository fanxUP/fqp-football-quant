from __future__ import annotations

from scripts.news_source_policy import resolve_source_policy


def test_official_football_domains_receive_system_owned_s_level() -> None:
    policy = resolve_source_policy("news.uefa.com")

    assert policy.source_level == "S"
    assert policy.source_type == "official"
    assert policy.enabled is True


def test_allowlisted_domestic_media_keeps_chinese_language_metadata() -> None:
    policy = resolve_source_policy("sports.sina.com.cn")

    assert policy.source_level == "B"
    assert policy.default_language == "zh"


def test_unknown_domain_is_kept_unverified_instead_of_being_trusted_by_ai() -> None:
    policy = resolve_source_policy("unknown-football.example")

    assert policy.source_level == "C"
    assert policy.source_type == "media"
    assert policy.enabled is True
