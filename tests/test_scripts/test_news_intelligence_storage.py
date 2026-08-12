from __future__ import annotations

from datetime import UTC, datetime

from scripts.news_intelligence_clients import NewsArticleCandidate
from scripts.news_intelligence_storage import match_candidate_to_official_matches


def test_candidate_links_with_verified_english_alias_instead_of_only_chinese_name() -> None:
    candidate = NewsArticleCandidate(
        provider_code="guardian",
        external_id="article-1",
        source_name="The Guardian Football",
        source_domain="theguardian.com",
        canonical_url="https://www.theguardian.com/football/article-1",
        title="Aston Villa prepare for PSG test",
        description="Unai Emery discusses the Paris Saint-Germain match.",
        language="en",
        published_at=datetime(2026, 8, 10, 8, tzinfo=UTC),
        raw_metadata={},
    )
    matches = [
        {
            "id": 7,
            "home_team_name": "巴黎圣日尔曼",
            "away_team_name": "阿斯顿维拉",
            "home_search_terms": ["巴黎圣日尔曼", "Paris Saint-Germain", "PSG"],
            "away_search_terms": ["阿斯顿维拉", "Aston Villa"],
        }
    ]

    linked = match_candidate_to_official_matches(candidate, matches)

    assert [match["id"] for match in linked] == [7]
