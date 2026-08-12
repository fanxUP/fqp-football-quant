"""Free-tier-aware query planning for football news providers.

The planner is deliberately pure: it does not call providers or the database.
Daily usage is enforced by the collector from persisted ingestion audit rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class ProviderPolicy:
    daily_request_budget: int
    requests_per_run: int
    max_results: int
    maximum_query_length: int
    minimum_interval_seconds: float
    publication_delay_hours: int
    lookback_hours: int
    requires_latin_terms: bool = False


@dataclass(frozen=True)
class NewsQueryBatch:
    query: str
    match_ids: tuple[int, ...]
    matches: tuple[dict[str, Any], ...]


# Official limits and delay behavior:
# - https://gnews.io/ and https://docs.gnews.io/error-handling
# - https://open-platform.theguardian.com/access/
# - https://newsapi.org/pricing
# Budgets intentionally retain headroom for diagnostics, retries and provider
# clock differences. Scheduler runs 12 times per day at two-hour intervals.
PROVIDER_POLICIES = {
    "gnews": ProviderPolicy(
        daily_request_budget=72,
        requests_per_run=6,
        max_results=10,
        maximum_query_length=190,
        minimum_interval_seconds=1.1,
        publication_delay_hours=12,
        lookback_hours=36,
    ),
    "guardian": ProviderPolicy(
        daily_request_budget=144,
        requests_per_run=12,
        max_results=50,
        maximum_query_length=450,
        minimum_interval_seconds=1.1,
        publication_delay_hours=0,
        lookback_hours=36,
        requires_latin_terms=True,
    ),
    "newsapi": ProviderPolicy(
        daily_request_budget=48,
        requests_per_run=4,
        max_results=100,
        maximum_query_length=480,
        minimum_interval_seconds=0.25,
        publication_delay_hours=24,
        lookback_hours=48,
    ),
}

_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


def _is_latin_term(value: str) -> bool:
    return bool(_LATIN_RE.search(value)) and not _CJK_RE.search(value)


def _deduplicated_terms(match: dict[str, Any], *, latin_only: bool) -> list[str]:
    raw_terms = [
        *match.get("home_search_terms", []),
        *match.get("away_search_terms", []),
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for raw in raw_terms:
        normalized = str(raw or "").strip().replace('"', "")
        key = normalized.casefold()
        if not normalized or key in seen or (latin_only and not _is_latin_term(normalized)):
            continue
        terms.append(normalized)
        seen.add(key)
    return terms


def _bounded_exact_query(terms: list[str], maximum_length: int) -> str:
    selected: list[str] = []
    for term in terms:
        candidate = " OR ".join([*selected, f'"{term}"'])
        if len(candidate) > maximum_length:
            break
        selected.append(f'"{term}"')
    return " OR ".join(selected)


def build_provider_query_batches(
    matches: list[dict[str, Any]],
    provider_code: str,
    *,
    rotation_slot: int,
    limit: int | None = None,
) -> list[NewsQueryBatch]:
    """Return a rotating, match-scoped query plan within one run's budget."""
    policy = PROVIDER_POLICIES[provider_code]
    eligible: list[NewsQueryBatch] = []
    for match in matches:
        terms = _deduplicated_terms(match, latin_only=policy.requires_latin_terms)
        query = _bounded_exact_query(terms, policy.maximum_query_length)
        if not query:
            continue
        match_id = int(match["id"])
        eligible.append(NewsQueryBatch(query, (match_id,), (match,)))
    if not eligible:
        return []
    requested_limit = policy.requests_per_run if limit is None else limit
    batch_limit = max(0, min(requested_limit, len(eligible)))
    if batch_limit == 0:
        return []
    start = (max(rotation_slot, 0) * batch_limit) % len(eligible)
    return [eligible[(start + offset) % len(eligible)] for offset in range(batch_limit)]


def provider_window(provider_code: str, observed_at: datetime) -> tuple[datetime, datetime]:
    """Apply each free plan's publication delay before its lookback window."""
    policy = PROVIDER_POLICIES[provider_code]
    end = observed_at - timedelta(hours=policy.publication_delay_hours)
    return end - timedelta(hours=policy.lookback_hours), end
