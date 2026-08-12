from __future__ import annotations

from typing import Any

import httpx

from scripts.news_intelligence_clients import GNewsClient, GuardianClient, NewsApiClient


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.url = ""
        self.kwargs: dict[str, Any] = {}

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.url = url
        self.kwargs = kwargs
        return httpx.Response(200, json=self.payload, request=httpx.Request("GET", url))


def test_newsapi_uses_everything_endpoint_and_header_key() -> None:
    transport = _FakeClient(
        {
            "articles": [
                {
                    "source": {"name": "Club Site"},
                    "title": "Team injury update",
                    "description": "Player unavailable",
                    "url": "https://club.example/news/1?utm_source=test",
                    "publishedAt": "2026-08-10T08:00:00Z",
                }
            ]
        }
    )

    articles = NewsApiClient("news-key", client=transport).search("Team injury")

    assert transport.url == "https://newsapi.org/v2/everything"
    assert transport.kwargs["headers"] == {"X-Api-Key": "news-key"}
    assert transport.kwargs["params"]["q"] == "Team injury"
    assert articles[0].canonical_url == "https://club.example/news/1"


def test_gnews_uses_documented_search_endpoint_and_api_key_parameter() -> None:
    transport = _FakeClient(
        {
            "articles": [
                {
                    "source": {"name": "Sports Desk", "url": "https://sports.example"},
                    "title": "Confirmed lineup",
                    "description": "Starting XI",
                    "url": "https://sports.example/lineup/2",
                    "publishedAt": "2026-08-10T09:00:00Z",
                    "lang": "en",
                }
            ]
        }
    )

    articles = GNewsClient("gnews-key", client=transport).search("Confirmed lineup")

    assert transport.url == "https://gnews.io/api/v4/search"
    assert transport.kwargs["headers"] == {}
    assert transport.kwargs["params"]["apikey"] == "gnews-key"
    assert transport.kwargs["params"]["sortby"] == "publishedAt"
    assert transport.kwargs["params"]["max"] == 10
    assert articles[0].source_domain == "sports.example"


def test_guardian_uses_football_content_api_and_normalizes_results() -> None:
    transport = _FakeClient(
        {
            "response": {
                "results": [
                    {
                        "id": "football/2026/aug/10/team-news",
                        "webTitle": "Team news confirmed",
                        "webUrl": "https://www.theguardian.com/football/2026/aug/10/team-news",
                        "webPublicationDate": "2026-08-10T10:00:00Z",
                        "fields": {"trailText": "<strong>Striker</strong> unavailable"},
                    }
                ]
            }
        }
    )

    articles = GuardianClient("guardian-key", client=transport).search("Team news")

    assert transport.url == "https://content.guardianapis.com/search"
    assert transport.kwargs["params"]["api-key"] == "guardian-key"
    assert transport.kwargs["params"]["section"] == "football"
    assert transport.kwargs["params"]["show-fields"] == "trailText"
    assert articles[0].provider_code == "guardian"
    assert articles[0].external_id == "football/2026/aug/10/team-news"
    assert articles[0].description == "Striker unavailable"
    assert articles[0].source_domain == "theguardian.com"
