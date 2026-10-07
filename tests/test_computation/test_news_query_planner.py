from __future__ import annotations

from datetime import UTC, datetime

from scripts.news_query_planner import (
    PROVIDER_POLICIES,
    build_provider_query_batches,
    provider_window,
)


def _match(match_id: int, home: list[str], away: list[str]) -> dict[str, object]:
    return {
        "id": match_id,
        "home_team_name": home[0],
        "away_team_name": away[0],
        "home_search_terms": home,
        "away_search_terms": away,
    }


def test_free_tier_policies_keep_daily_reserve_and_documented_result_limits() -> None:
    assert PROVIDER_POLICIES["gnews"].daily_request_budget == 72
    assert PROVIDER_POLICIES["gnews"].max_results == 10
    assert PROVIDER_POLICIES["gnews"].minimum_interval_seconds > 1
    assert PROVIDER_POLICIES["guardian"].daily_request_budget == 144
    assert PROVIDER_POLICIES["guardian"].max_results == 50
    assert PROVIDER_POLICIES["newsapi"].daily_request_budget == 48


def test_query_batches_prefer_english_aliases_but_keep_chinese_for_global_sources() -> None:
    matches = [
        _match(1, ["巴黎圣日尔曼", "Paris Saint-Germain", "PSG"], ["阿斯顿维拉", "Aston Villa"])
    ]

    guardian = build_provider_query_batches(matches, "guardian", rotation_slot=0, limit=12)
    gnews = build_provider_query_batches(matches, "gnews", rotation_slot=0, limit=6)

    assert guardian[0].match_ids == (1,)
    assert '"Paris Saint-Germain"' in guardian[0].query
    assert '"巴黎圣日尔曼"' not in guardian[0].query
    assert '"巴黎圣日尔曼"' in gnews[0].query
    assert '"Aston Villa"' in gnews[0].query


def test_query_batch_rotation_eventually_covers_matches_beyond_each_run_limit() -> None:
    matches = [
        _match(index, [f"球队{index}", f"Team {index}"], [f"客队{index}", f"Away {index}"])
        for index in range(1, 10)
    ]

    first = build_provider_query_batches(matches, "gnews", rotation_slot=0, limit=3)
    second = build_provider_query_batches(matches, "gnews", rotation_slot=1, limit=3)

    assert [batch.match_ids for batch in first] == [(1,), (2,), (3,)]
    assert [batch.match_ids for batch in second] == [(4,), (5,), (6,)]


def test_free_tier_delay_is_reflected_in_each_provider_window() -> None:
    observed_at = datetime(2026, 8, 12, 8, tzinfo=UTC)

    gnews_start, gnews_end = provider_window("gnews", observed_at)
    newsapi_start, newsapi_end = provider_window("newsapi", observed_at)

    assert (observed_at - gnews_end).total_seconds() == 12 * 3600
    assert (gnews_end - gnews_start).total_seconds() == 36 * 3600
    assert (observed_at - newsapi_end).total_seconds() == 24 * 3600
    assert (newsapi_end - newsapi_start).total_seconds() == 48 * 3600


def test_guardian_skips_matches_without_latin_aliases_to_avoid_wasting_quota() -> None:
    matches = [_match(1, ["未知主队"], ["未知客队"])]

    assert build_provider_query_batches(matches, "guardian", rotation_slot=0) == []
