"""Conservative adapters for NewsAPI, GNews and Guardian football search.

Official API references:
- https://newsapi.org/docs/endpoints/everything
- https://docs.gnews.io/endpoints/search-endpoint
- https://open-platform.theguardian.com/documentation/search
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx

from scripts.news_query_planner import PROVIDER_POLICIES
from scripts.request_quota import RedisQuotaLedger
from scripts.request_transport import GovernedJsonClient

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
        [
            (key, item)
            for key, item in parse_qsl(parsed.query)
            if key.lower() not in _TRACKING_PARAMS
        ]
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

    def __init__(
        self,
        api_key: str,
        *,
        client: Any | None = None,
        ledger: RedisQuotaLedger | None = None,
        max_attempts: int = 1,
    ) -> None:
        self.api_key = api_key
        self._owns_client = client is None
        self._client = (
            client if client is not None else httpx.Client(timeout=20.0, follow_redirects=False)
        )
        self._transport = GovernedJsonClient(
            self.provider_code,
            api_key,
            client=self._client,
            ledger=ledger,
            max_attempts=max_attempts,
            min_interval_seconds=PROVIDER_POLICIES[self.provider_code].minimum_interval_seconds,
        )

    @property
    def last_request_meta(self) -> dict[str, Any]:
        return dict(self._transport.last_request_meta)

    @property
    def total_sends(self) -> int:
        return self._transport.total_sends

    def close(self) -> None:
        self._transport.close()
        if self._owns_client:
            self._client.close()

    def _params(self, query: str, start: datetime | None, end: datetime | None) -> dict[str, Any]:
        raise NotImplementedError

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key}

    def search(
        self,
        query: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[NewsArticleCandidate]:
        payload = self._transport.get(
            self.endpoint,
            headers=self._headers(),
            params=self._params(query, start, end),
        )
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
        params: dict[str, Any] = {
            "q": query,
            "sortBy": "publishedAt",
            "pageSize": PROVIDER_POLICIES[self.provider_code].max_results,
        }
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        return params


class GNewsClient(_SearchClient):
    provider_code = "gnews"
    endpoint = "https://gnews.io/api/v4/search"

    def _headers(self) -> dict[str, str]:
        return {}

    def _params(self, query: str, start: datetime | None, end: datetime | None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "q": query,
            "sortby": "publishedAt",
            "max": PROVIDER_POLICIES[self.provider_code].max_results,
            "apikey": self.api_key,
        }
        if start:
            params["from"] = start.isoformat()
        if end:
            params["to"] = end.isoformat()
        return params


class GuardianClient(_SearchClient):
    """The Guardian Open Platform content search, restricted to football."""

    provider_code = "guardian"
    endpoint = "https://content.guardianapis.com/search"

    def search(
        self,
        query: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[NewsArticleCandidate]:
        params: dict[str, Any] = {
            "q": query,
            "section": "football",
            "order-by": "newest",
            "page-size": PROVIDER_POLICIES[self.provider_code].max_results,
            "show-fields": "trailText",
            "api-key": self.api_key,
        }
        if start:
            params["from-date"] = start.date().isoformat()
        if end:
            params["to-date"] = end.date().isoformat()
        payload = self._transport.get(self.endpoint, headers={}, params=params)
        body = payload.get("response", {}) if isinstance(payload, dict) else {}
        raw_results = body.get("results", []) if isinstance(body, dict) else []
        candidates: list[NewsArticleCandidate] = []
        for raw in raw_results:
            if not isinstance(raw, dict):
                continue
            url = canonicalize_article_url(str(raw.get("webUrl") or ""))
            title = str(raw.get("webTitle") or "").strip()
            published_at = raw.get("webPublicationDate")
            if not url or not title or not published_at:
                continue
            raw_fields = raw.get("fields")
            fields: dict[str, Any] = raw_fields if isinstance(raw_fields, dict) else {}
            trail_text = str(fields.get("trailText") or "")
            description = html.unescape(re.sub(r"<[^>]+>", " ", trail_text))
            description = " ".join(description.split())
            candidates.append(
                NewsArticleCandidate(
                    provider_code=self.provider_code,
                    external_id=str(raw.get("id") or hashlib.sha256(url.encode()).hexdigest()),
                    source_name="The Guardian Football",
                    source_domain="theguardian.com",
                    canonical_url=url,
                    title=title,
                    description=description,
                    language="en",
                    published_at=_published_at(published_at),
                    raw_metadata={"sectionId": raw.get("sectionId")},
                )
            )
        return candidates
