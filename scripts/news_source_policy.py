"""System-owned source trust policy; model output can never raise trust."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsSourcePolicy:
    publisher_domain: str
    display_name: str
    source_level: str
    source_type: str
    default_language: str | None
    enabled: bool = True


_POLICY_ROWS = (
    ("thecfa.cn", "中国足球协会", "S", "official", "zh"),
    ("fifa.com", "FIFA", "S", "official", "en"),
    ("uefa.com", "UEFA", "S", "official", "en"),
    ("the-afc.com", "AFC", "S", "official", "en"),
    ("premierleague.com", "Premier League", "S", "official", "en"),
    ("laliga.com", "LaLiga", "S", "official", "es"),
    ("bundesliga.com", "Bundesliga", "S", "official", "de"),
    ("legaseriea.it", "Lega Serie A", "S", "official", "it"),
    ("ligue1.com", "Ligue 1", "S", "official", "fr"),
    ("reuters.com", "Reuters", "A", "media", "en"),
    ("news.cn", "新华社", "A", "media", "zh"),
    ("bbc.co.uk", "BBC Sport", "B", "media", "en"),
    ("theguardian.com", "The Guardian Football", "B", "media", "en"),
    ("espn.com", "ESPN", "B", "media", "en"),
    ("skysports.com", "Sky Sports", "B", "media", "en"),
    ("sports.sina.com.cn", "新浪体育", "B", "media", "zh"),
    ("dongqiudi.com", "懂球帝", "B", "media", "zh"),
    ("sports.163.com", "网易体育", "C", "media", "zh"),
    ("sports.sohu.com", "搜狐体育", "C", "media", "zh"),
)
DEFAULT_SOURCE_POLICIES = tuple(NewsSourcePolicy(*row) for row in _POLICY_ROWS)


def load_news_source_policies(conn: Any) -> tuple[NewsSourcePolicy, ...]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT publisher_domain, display_name, source_level, source_type,
                   default_language, enabled
            FROM news_source_policies
            ORDER BY length(publisher_domain) DESC, publisher_domain
            """
        )
        rows = cur.fetchall()
    return tuple(NewsSourcePolicy(*row) for row in rows)


def resolve_source_policy(
    publisher_domain: str,
    policies: tuple[NewsSourcePolicy, ...] = DEFAULT_SOURCE_POLICIES,
) -> NewsSourcePolicy:
    domain = publisher_domain.strip().lower().removeprefix("www.").rstrip(".")
    matches = [
        policy
        for policy in policies
        if domain == policy.publisher_domain or domain.endswith(f".{policy.publisher_domain}")
    ]
    if matches:
        return max(matches, key=lambda item: len(item.publisher_domain))
    return NewsSourcePolicy(domain, "", "C", "media", None)
