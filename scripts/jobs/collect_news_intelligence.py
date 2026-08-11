"""Conservative football-news discovery for upcoming official matches."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.news_intelligence_clients import GNewsClient, NewsApiClient
from scripts.news_intelligence_storage import load_news_watch_matches, store_news_candidates

MAX_QUERY_LENGTH = 190


def build_watch_query(matches: list[dict[str, Any]]) -> str:
    terms: list[str] = []
    seen: set[str] = set()
    for match in matches:
        for name in (match.get("home_team_name"), match.get("away_team_name")):
            normalized = str(name or "").strip().replace('"', "")
            normalized_key = normalized.casefold()
            if not normalized or normalized_key in seen:
                continue
            candidate = " OR ".join([*terms, f'"{normalized}"'])
            if len(candidate) > MAX_QUERY_LENGTH:
                return " OR ".join(terms)
            terms.append(f'"{normalized}"')
            seen.add(normalized_key)
    return " OR ".join(terms)


def run() -> dict[str, Any]:
    if os.getenv("FQP_NEWS_COLLECTION_ENABLED", "false").lower() != "true":
        return {"status": "skipped", "reason": "collection_disabled"}
    provider_keys = {
        "newsapi": os.getenv("NEWSAPI_API_KEY", "").strip(),
        "gnews": os.getenv("GNEWS_API_KEY", "").strip(),
    }
    if not any(provider_keys.values()):
        return {"status": "skipped", "reason": "no_provider_keys"}
    with get_db() as conn:
        matches = load_news_watch_matches(conn)
        if not matches:
            return {"status": "skipped", "reason": "no_official_matches"}
        query = build_watch_query(matches)
        if not query:
            return {"status": "skipped", "reason": "no_team_terms"}
        now = datetime.now(UTC)
        totals = {"inserted": 0, "duplicates": 0, "linked": 0, "providers": 0}
        clients: list[NewsApiClient | GNewsClient] = []
        if provider_keys["newsapi"]:
            clients.append(NewsApiClient(provider_keys["newsapi"]))
        if provider_keys["gnews"]:
            clients.append(GNewsClient(provider_keys["gnews"]))
        for client in clients:
            candidates = client.search(query, start=now - timedelta(hours=8), end=now)
            stored = store_news_candidates(conn, candidates, matches, observed_at=now)
            totals["providers"] += 1
            for key in ("inserted", "duplicates", "linked"):
                totals[key] += stored[key]
    return {"status": "ok", **totals}


if __name__ == "__main__":
    print(run())
