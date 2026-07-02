"""TheOddsAPI v4 REST client.

Free tier: 500 requests/month, apiKey query parameter.
Covers multi-bookmaker odds (h2h, spreads, totals), scores, and events.

Key endpoints (v4):
  /sports                        → list all sports
  /sports/{sport}/odds           → current odds from multiple bookmakers
  /sports/{sport}/odds-history   → historical odds (limited on free tier)
  /sports/{sport}/scores         → scores and results
  /sports/{sport}/events         → upcoming events

Value for FQP:
  - Multi-bookmaker odds vs Sporttery official odds → market inefficiency detection
  - Historical odds for strategy backtesting
  - Odds movement tracking → market sentiment signals
  - Over/under + handicap markets for alternative betting angles
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

import httpx

# Football sport keys on TheOddsAPI
SOCCER_KEYS = {
    "england_premier_league": "soccer_england_premier_league",
    "england_championship": "soccer_england_efl_championship",
    "spain_la_liga": "soccer_spain_la_liga",
    "italy_serie_a": "soccer_italy_serie_a",
    "germany_bundesliga": "soccer_germany_bundesliga",
    "france_ligue_1": "soccer_france_ligue_one",
    "netherlands_eredivisie": "soccer_netherlands_eredivisie",
    "portugal_primeira_liga": "soccer_portugal_primeira_liga",
    "belgium_first_div_a": "soccer_belgium_first_div_a",
    "turkey_super_lig": "soccer_turkey_super_lig",
    "champions_league": "soccer_uefa_champions_league",
    "europa_league": "soccer_uefa_europa_league",
    "mls": "soccer_usa_mls",
    "brazil_serie_a": "soccer_brazil_campeonato_brasileiro",
    "argentina_primera": "soccer_argentina_primera_division",
    "japan_j1": "soccer_japan_j1_league",
    "korea_k_league_1": "soccer_korea_kleague1",
    "australia_a_league": "soccer_australia_aleague",
    "uefa_euro": "soccer_uefa_european_championship",
    "fifa_world_cup": "soccer_fifa_world_cup",
}


class TheOddsClient:
    """HTTP client for the-odds-api.com v4."""

    BASE_URL = "https://api.the-odds-api.com/v4/"

    # 500 requests/month on free tier
    _monthly_call_limit = 500

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        min_interval: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key or os.getenv("THEODDS_API_KEY", "")
        if not self._api_key:
            raise ValueError("THEODDS_API_KEY is required (env or constructor)")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={
                "Accept": "application/json",
            },
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_time = 0.0
        self._call_count_this_month = 0
        self._month_start = datetime.utcnow().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _check_monthly_quota(self) -> None:
        """Warn if approaching monthly limit. Auto-reset counter if month changed."""
        now = datetime.utcnow()
        if now.month != self._month_start.month or now.year != self._month_start.year:
            self._call_count_this_month = 0
            self._month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        self._call_count_this_month += 1

        if self._call_count_this_month > self._monthly_call_limit * 0.8:
            print(
                f"[theodds] WARNING: {self._call_count_this_month}/{self._monthly_call_limit} "
                f"monthly calls used"
            )
        if self._call_count_this_month >= self._monthly_call_limit:
            print(f"[theodds] FATAL: monthly call limit ({self._monthly_call_limit}) reached")

    def _request(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """GET request with apiKey injected and exponential backoff."""
        self._rate_limit()
        self._check_monthly_quota()

        params = dict(params or {})
        params["apiKey"] = self._api_key

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(
                    f"[theodds] GET {path} params="
                    + str({k: v for k, v in params.items() if k != "apiKey"})
                    + " "
                    f"(attempt {attempt}, call #{self._call_count_this_month})"
                )
                resp = self._client.get(path, params=params)
                self._last_request_time = time.monotonic()

                # Track quota from response headers
                remaining = resp.headers.get("x-requests-remaining")
                used = resp.headers.get("x-requests-used")
                if remaining and used:
                    print(f"[theodds] quota: {used}/{int(remaining) + int(used)} used this month")

                if resp.status_code == 429:
                    wait = 60
                    print(f"[theodds] rate limited (429), waiting {wait}s...")
                    time.sleep(wait)
                    continue

                if resp.status_code == 401:
                    raise RuntimeError(
                        "TheOddsClient: API key rejected (401). Check THEODDS_API_KEY."
                    )

                if resp.status_code == 422:
                    # Usually means no odds available for the requested parameters
                    data = resp.json()
                    print(f"[theodds] 422: {data}")
                    return []  # type: ignore[return-value]

                resp.raise_for_status()
                data = resp.json()
                print(f"[theodds] GET {path} → {resp.status_code}")
                return data  # type: ignore[return-value]
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                last_error = e
                print(f"[theodds] GET {path} error (attempt {attempt}): {e}")
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[theodds] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"TheOddsClient: {self._max_retries} attempts failed for {path}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Public API — Sports
    # ------------------------------------------------------------------

    def list_sports(self) -> list[dict[str, Any]]:
        """List all available sports and their keys.

        Returns list of {key, group, title, description, active, has_outrights}.
        """
        return self._request("sports")  # type: ignore[return-value]

    def list_soccer_leagues(self) -> list[dict[str, Any]]:
        """List only soccer/football leagues."""
        sports = self.list_sports()
        return [s for s in sports if s.get("key", "").startswith("soccer_")]

    # ------------------------------------------------------------------
    # Public API — Odds
    # ------------------------------------------------------------------

    def get_odds(
        self,
        sport_key: str,
        regions: str = "eu",  # European bookmakers
        markets: str = "h2h",  # h2h, spreads, totals — comma-separated
        odds_format: str = "decimal",
        date_format: str = "iso",
        bookmakers: str | None = None,
        event_ids: str | None = None,  # comma-separated event IDs
    ) -> list[dict[str, Any]]:
        """Get current odds for a sport from multiple bookmakers.

        Args:
            sport_key: e.g. 'soccer_england_premier_league' (use SOCCER_KEYS).
            regions: 'eu', 'uk', 'us', 'au' — bookmaker regions.
            markets: 'h2h', 'spreads', 'totals' — comma-separated.
            odds_format: 'decimal' or 'american'.
            date_format: 'iso' or 'unix'.
            bookmakers: Comma-separated bookmaker keys to filter.
            event_ids: Comma-separated event IDs to filter.

        Returns list of matches, each with bookmakers and their odds.
        """
        params: dict[str, Any] = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        if event_ids:
            params["eventIds"] = event_ids

        return self._request(f"sports/{sport_key}/odds", params=params)  # type: ignore[return-value]

    def get_h2h_odds(
        self,
        sport_key: str,
        regions: str = "eu",
        bookmakers: str | None = None,
        event_ids: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience: get match-winner (1X2) odds from European bookmakers."""
        return self.get_odds(
            sport_key=sport_key,
            regions=regions,
            markets="h2h",
            bookmakers=bookmakers,
            event_ids=event_ids,
        )

    def get_all_markets(
        self,
        sport_key: str,
        regions: str = "eu",
        bookmakers: str | None = None,
        event_ids: str | None = None,
    ) -> list[dict[str, Any]]:
        """Convenience: get all major markets (h2h, spreads, totals)."""
        return self.get_odds(
            sport_key=sport_key,
            regions=regions,
            markets="h2h,spreads,totals",
            bookmakers=bookmakers,
            event_ids=event_ids,
        )

    # ------------------------------------------------------------------
    # Public API — Historical Odds
    # ------------------------------------------------------------------

    def get_odds_history(
        self,
        sport_key: str,
        date: str,  # YYYY-MM-DD
        regions: str = "eu",
        markets: str = "h2h,spreads,totals",
        odds_format: str = "decimal",
        date_format: str = "iso",
        event_ids: str | None = None,
        bookmakers: str | None = None,
    ) -> dict[str, Any]:
        """Get historical odds for a specific date and sport.

        Limited on free tier — may not include all dates or bookmakers.
        """
        params: dict[str, Any] = {
            "regions": regions,
            "markets": markets,
            "oddsFormat": odds_format,
            "dateFormat": date_format,
            "date": date,
        }
        if event_ids:
            params["eventIds"] = event_ids
        if bookmakers:
            params["bookmakers"] = bookmakers

        return self._request(f"sports/{sport_key}/odds-history", params=params)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API — Scores
    # ------------------------------------------------------------------

    def get_scores(
        self,
        sport_key: str,
        days_from: int = 1,
        date_format: str = "iso",
        event_ids: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent scores and results.

        Args:
            sport_key: e.g. 'soccer_england_premier_league'.
            days_from: How many days back to fetch results for (default 1).
            event_ids: Comma-separated event IDs.
        """
        params: dict[str, Any] = {
            "daysFrom": days_from,
            "dateFormat": date_format,
        }
        if event_ids:
            params["eventIds"] = event_ids

        return self._request(f"sports/{sport_key}/scores", params=params)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API — Events
    # ------------------------------------------------------------------

    def get_events(
        self,
        sport_key: str,
        date_format: str = "iso",
        event_ids: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get upcoming events for a sport.

        Returns event id, home/away team, commence time.
        """
        params: dict[str, Any] = {"dateFormat": date_format}
        if event_ids:
            params["eventIds"] = event_ids

        return self._request(f"sports/{sport_key}/events", params=params)  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Public API — Event Odds (single event)
    # ------------------------------------------------------------------

    def get_event_odds(
        self,
        sport_key: str,
        event_id: str,
        regions: str = "eu",
        markets: str = "h2h,spreads,totals",
        odds_format: str = "decimal",
        bookmakers: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get odds for a single event."""
        return self.get_odds(
            sport_key=sport_key,
            regions=regions,
            markets=markets,
            odds_format=odds_format,
            bookmakers=bookmakers,
            event_ids=event_id,
        )

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    @property
    def call_count_this_month(self) -> int:
        return self._call_count_this_month

    @property
    def monthly_limit(self) -> int:
        return self._monthly_call_limit

    def reset_call_count(self) -> None:
        """Reset monthly counter manually."""
        self._call_count_this_month = 0

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()
