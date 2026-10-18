"""Conservative football-news discovery for upcoming official matches."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from zoneinfo import ZoneInfo

from apps.backend.src.db import get_db
from scripts.news_intelligence_clients import GNewsClient, GuardianClient, NewsApiClient
from scripts.news_intelligence_storage import (
    filter_match_relevant_candidates,
    load_news_watch_matches,
    record_news_ingestion_request,
    store_news_candidates,
)
from scripts.news_query_planner import (
    PROVIDER_POLICIES,
    NewsQueryBatch,
    build_provider_query_batches,
    provider_window,
)


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


def collect_provider_batches(
    client: Any,
    batches: list[NewsQueryBatch],
    *,
    observed_at: datetime,
    store: Callable[[list[Any], list[dict[str, Any]]], dict[str, int]],
    audit: Callable[[dict[str, Any]], None],
    wait: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Audit logical batches separately from measured transport attempts.

    Audit rows are evidence, never permission to send or a quota balance. Legacy
    test/ad-hoc clients without counters are explicitly marked unmeasured.
    """
    provider_code = str(client.provider_code)
    policy = PROVIDER_POLICIES[provider_code]
    start, end = provider_window(provider_code, observed_at)
    totals = {
        "requests": 0,
        "sentRequests": 0,
        "reusedRequests": 0,
        "blockedRequests": 0,
        "unmeasuredRequests": 0,
        "failedRequests": 0,
        "zeroResultQueries": 0,
        "candidates": 0,
        "inserted": 0,
        "duplicates": 0,
        "linked": 0,
        "filtered": 0,
    }
    errors: list[dict[str, str]] = []
    for index, batch in enumerate(batches):
        if index:
            wait(policy.minimum_interval_seconds)
        request_started = datetime.now(UTC)
        candidates: list[Any] = []
        stored = {"inserted": 0, "duplicates": 0, "linked": 0, "filtered": 0}
        error_message: str | None = None
        status = "completed"
        sent_before = getattr(client, "total_sends", None)
        try:
            candidates = client.search(batch.query, start=start, end=end)
            relevant_candidates, prefiltered = filter_match_relevant_candidates(
                candidates, list(batch.matches)
            )
            stored = store(relevant_candidates, list(batch.matches))
            stored["filtered"] = stored.get("filtered", 0) + prefiltered
        except Exception as exc:
            status = "failed"
            error_message = type(exc).__name__
            totals["failedRequests"] += 1
            errors.append({"provider": provider_code, "error": error_message})
        finished_at = datetime.now(UTC)
        sent_after = getattr(client, "total_sends", None)
        sent = (
            sent_after - sent_before
            if type(sent_before) is int and type(sent_after) is int and sent_after >= sent_before
            else None
        )
        measured = sent is not None
        if sent is None:
            totals["unmeasuredRequests"] += 1
        else:
            totals["sentRequests"] += sent
            totals["blockedRequests"] += int(status == "failed" and sent == 0)
        # Allowlist only bounded diagnostics; never serialize provider payloads,
        # request URLs or query-string API keys into the existing audit JSON.
        raw_meta = getattr(client, "last_request_meta", {})
        request_meta: dict[str, Any] = {"attemptsSent": sent, "measured": measured}
        for key in (
            "http_status",
            "quota_day_sent",
            "remaining",
            "minute_remaining",
            "fetched_at_ms",
            "age_ms",
        ):
            value = raw_meta.get(key) if isinstance(raw_meta, dict) else None
            if type(value) is int and value >= 0:
                request_meta[key] = value
        reuse_status = raw_meta.get("reuse_status") if isinstance(raw_meta, dict) else None
        if reuse_status in ("fetched", "cache_hit", "coalesced", "not_stored", "unavailable"):
            request_meta["reuse_status"] = reuse_status
            totals["reusedRequests"] += int(
                status == "completed" and sent == 0 and reuse_status in ("cache_hit", "coalesced")
            )
        totals["requests"] += 1
        totals["candidates"] += len(candidates)
        totals["zeroResultQueries"] += int(status == "completed" and not candidates)
        for key in ("inserted", "duplicates", "linked", "filtered"):
            totals[key] += stored.get(key, 0)
        audit(
            {
                "provider_code": provider_code,
                "started_at": request_started,
                "finished_at": finished_at,
                "status": status,
                "requested_count": len(candidates),
                "inserted_count": stored.get("inserted", 0),
                "duplicate_count": stored.get("duplicates", 0),
                "error_message": error_message,
                "cursor_state": {
                    "querySha256": sha256(batch.query.encode()).hexdigest(),
                    "matchIds": list(batch.match_ids),
                    "transport": request_meta,
                },
            }
        )
    if totals["failedRequests"] == totals["requests"] and totals["requests"]:
        status = "failed"
    elif totals["failedRequests"]:
        status = "partial"
    elif not totals["candidates"]:
        status = "empty"
    else:
        status = "ok"
    return {"status": status, **totals, "errors": errors}


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
    skipped_providers: list[dict[str, str]] = []
    if (
        provider_keys["newsapi"]
        and os.getenv("FQP_NEWSAPI_AUTOMATION_ENABLED", "false").lower() != "true"
    ):
        provider_keys["newsapi"] = ""
        skipped_providers.append({"provider": "newsapi", "reason": "free_plan_development_only"})
    if not any(provider_keys.values()):
        return {
            "status": "skipped",
            "reason": "no_eligible_provider_keys",
            "skippedProviders": skipped_providers,
        }
    now = datetime.now(UTC)
    with get_db() as conn:
        matches = load_news_watch_matches(conn)
        if not matches:
            return {
                "status": "skipped",
                "reason": "no_official_matches",
                "skippedProviders": skipped_providers,
            }

    timezone_name = os.getenv("FQP_TIMEZONE", "Asia/Shanghai")
    rotation_slot = now.astimezone(ZoneInfo(timezone_name)).hour // 2
    provider_results: dict[str, dict[str, Any]] = {}
    for client in build_collection_clients(provider_keys):
        provider_code = str(client.provider_code)
        policy = PROVIDER_POLICIES[provider_code]

        def store(candidates: list[Any], batch_matches: list[dict[str, Any]]) -> dict[str, int]:
            with get_db() as conn:
                return store_news_candidates(conn, candidates, batch_matches, observed_at=now)

        def audit(payload: dict[str, Any]) -> None:
            with get_db() as conn:
                record_news_ingestion_request(conn, payload)

        try:
            batches = build_provider_query_batches(
                matches,
                provider_code,
                rotation_slot=rotation_slot,
                limit=policy.requests_per_run,
            )
            if not batches:
                provider_results[provider_code] = {
                    "status": "skipped",
                    "reason": "no_eligible_team_aliases",
                }
                continue
            result = collect_provider_batches(
                client,
                batches,
                observed_at=now,
                store=store,
                audit=audit,
            )
            result["planningDailyBudget"] = policy.daily_request_budget
            result["quotaSource"] = "shared_account_ledger"
            provider_results[provider_code] = result
        finally:
            client.close()

    completed_results = [
        result for result in provider_results.values() if result.get("requests", 0)
    ]
    total_candidates = sum(int(result.get("candidates", 0)) for result in completed_results)
    failed_results = [result for result in completed_results if result["status"] == "failed"]
    partial_results = [result for result in completed_results if result["status"] == "partial"]
    if completed_results and len(failed_results) == len(completed_results):
        status = "failed"
    elif failed_results or partial_results:
        status = "partial"
    elif total_candidates == 0:
        status = "empty"
    else:
        status = "ok"
    return {
        "status": status,
        "providers": provider_results,
        "skippedProviders": skipped_providers,
        "candidates": total_candidates,
        "inserted": sum(int(result.get("inserted", 0)) for result in completed_results),
        "linked": sum(int(result.get("linked", 0)) for result in completed_results),
    }


if __name__ == "__main__":
    print(run())
