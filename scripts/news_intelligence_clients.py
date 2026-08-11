"""Conservative adapters for NewsAPI Everything and GNews Search.

Official API references:
- https://newsapi.org/docs/endpoints/everything
- https://docs.gnews.io/endpoints/search-endpoint
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

_TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "ref",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


@dataclass(frozen=True)
class NewsArticleCandidate:
    provider_code: str
    external_id: str
    source_name: str
    source_domain: str
    canonical_url: str
    title: str
    description: str
    language: str | None
    published_at: datetime
    raw_metadata: dict[str, Any]


def canonicalize_article_url(value: str) -> str:
    parsed = urlparse(value.strip())
    query = urlencode(
        [(key, item) for key, item in parse_qsl(parsed.query) if key.lower() not in _TRACKING_PARAMS]
    )
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, "", query, ""))


def _published_at(value: object) -> datetime:
    normalized = str(value or "").strip().replace("Z", "+00:00")
    if not normalized:
        raise ValueError("新闻缺少发布时间")
    return datetime.fromisoformat(normalized)


def _candidate(provider_code: str, article: dict[str, Any]) -> NewsArticleCandidate:
    raw_source = article.get("source")
    source = raw_source if isinstance(raw_source, dict) else {}
    canonical_url = canonicalize_article_url(str(article.get("url") or ""))
    if not canonical_url or not urlparse(canonical_url).netloc:
        raise ValueError("新闻缺少有效原文地址")
    source_url = str(source.get("url") or canonical_url)
    source_domain = urlparse(source_url).netloc.lower().removeprefix("www.")
    title = str(article.get("title") or "").strip()
    if not title:
        raise ValueError("新闻缺少标题")
    external_id = hashlib.sha256(f"{provider_code}|{canonical_url}".encode()).hexdigest()
    return NewsArticleCandidate(
        provider_code=provider_code,
        external_id=external_id,
        source_name=str(source.get("name") or source_domain),
        source_domain=source_domain,
        canonical_url=canonical_url,
        title=title,
        description=str(article.get("description") or "").strip(),
        language=str(article.get("lang") or "").strip() or None,
        published_at=_published_at(article.get("publishedAt")),
        raw_metadata={"source": source, "image": article.get("urlToImage") or article.get("image")},
    )


class _SearchClient:
    provider_code: str
    endpoint: str

    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        self.api_key = api_key
        self._client = client or httpx.Client(timeout=20.0, follow_redirects=False)

    def _params(self, query: str, start: datetime | None, end: datetime | None) -> dict[str, Any]:
        raise NotImplementedError

    def search(
        self,
        query: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[NewsArticleCandidate]:
        response = self._client.get(
            self.endpoint,
            headers={"X-Api-Key": self.api_key},
            params=self._params(query, start, end),
        )
        response.raise_for_status()
        payload = response.json()
        raw_articles = payload.get("articles", []) if isinstance(payload, dict) else []
        candidates: list[NewsArticleCandidate] = []
        for raw in raw_articles:
            if not isinstance(raw, dict):
                continue
            try:
                candidates.append(_candidate(self.provider_code, raw))
            except ValueError:
                continue
        return candidates


class NewsApiClient(_SearchClient):
    provider_code = "newsapi"
    endpoint = "https://newsapi.org/v2/everything"

    def _params(self, query: str, start: datetime | None, end: datetime | None) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "sortBy": "publishedAt", "pageSize": 100}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        return params


class GNewsClient(_SearchClient):
    provider_code = "gnews"
    endpoint = "https://gnews.io/api/v4/search"

    def _params(self, query: str, start: datetime | None, end: datetime | None) -> dict[str, Any]:
        params: dict[str, Any] = {"q": query, "sortby": "publishedAt", "max": 100}
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        return params
