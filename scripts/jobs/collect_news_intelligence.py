"""Conservative football-news discovery for upcoming official matches."""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from apps.backend.src.db import get_db
from scripts.news_intelligence_clients import GNewsClient, GuardianClient, NewsApiClient
from scripts.news_intelligence_storage import load_news_watch_matches, store_news_candidates

MAX_QUERY_LENGTH = 190


def build_collection_clients(provider_keys: dict[str, str]) -> list[Any]:
    clients: list[Any] = []
    if provider_keys.get("newsapi"):
        clients.append(NewsApiClient(provider_keys["newsapi"]))
    if provider_keys.get("gnews"):
        clients.append(GNewsClient(provider_keys["gnews"]))
    if provider_keys.get("guardian"):
        clients.append(GuardianClient(provider_keys["guardian"]))
    return clients


def collect_from_clients(
    clients: list[Any],
    *,
    query: str,
    matches: list[dict[str, Any]],
    observed_at: datetime,
    store: Callable[[list[Any]], dict[str, int]],
) -> dict[str, Any]:
    """Isolate upstream failures so one source cannot discard other results."""
    totals = {
        "inserted": 0,
        "duplicates": 0,
        "linked": 0,
        "filtered": 0,
        "providers": 0,
        "failedProviders": 0,
    }
    errors: list[dict[str, str]] = []
    for client in clients:
        try:
            candidates = client.search(
                query,
                start=observed_at - timedelta(hours=8),
                end=observed_at,
            )
            stored = store(candidates)
        except Exception as exc:
            totals["failedProviders"] += 1
            errors.append(
                {
                    "provider": str(getattr(client, "provider_code", "unknown"))[:64],
                    "error": type(exc).__name__,
                }
            )
            continue
        totals["providers"] += 1
        for key in ("inserted", "duplicates", "linked", "filtered"):
            totals[key] += stored.get(key, 0)
    status = "ok"
    if totals["failedProviders"]:
        status = "partial" if totals["providers"] else "failed"
    return {"status": status, **totals, "errors": errors}


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
        "guardian": os.getenv("GUARDIAN_API_KEY", "").strip(),
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
        clients = build_collection_clients(provider_keys)
        return collect_from_clients(
            clients,
            query=query,
            matches=matches,
            observed_at=now,
            store=lambda candidates: store_news_candidates(
                conn, candidates, matches, observed_at=now
            ),
        )


if __name__ == "__main__":
    print(run())
