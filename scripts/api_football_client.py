"""API-Football v3 REST client.

Free tier: 100 calls/day, x-apisports-key header.
Wider league coverage than football-data.org, includes injuries and lineups.

Key endpoints:
  /teams          → team info + venue
  /players        → player info + season statistics
  /fixtures       → match fixtures with events, lineups, stats
  /injuries       → injury data (limited on free tier)
  /odds           → betting odds (limited on free tier)
  /standings      → league standings
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx


class ApiFootballClient:
    """HTTP client for v3.football.api-sports.io."""

    BASE_URL = "https://v3.football.api-sports.io/"

    # 100 calls/day on free tier → track usage locally
    _daily_call_limit = 100

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        min_interval: float = 1.0,
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        if not self._api_key:
            raise ValueError("API_FOOTBALL_KEY is required (env or constructor)")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={
                "x-apisports-key": self._api_key,
                "Accept": "application/json",
            },
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_time = 0.0
        self._call_count_today = 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._rate_limit()
        self._call_count_today += 1

        if self._call_count_today > self._daily_call_limit:
            print(
                f"[api-football] WARNING: daily call limit ({self._daily_call_limit}) "
                f"exceeded ({self._call_count_today} calls so far)"
            )

        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(
                    f"[api-football] GET {path} params={params} "
                    f"(attempt {attempt}, call #{self._call_count_today})"
                )
                resp = self._client.get(path, params=params)
                self._last_request_time = time.monotonic()

                # Handle rate limit headers
                remaining = resp.headers.get("x-ratelimit-requests-remaining")
                if remaining:
                    remaining = int(remaining)
                    if remaining < 5:
                        print(f"[api-football] low quota: {remaining} calls remaining today")

                resp.raise_for_status()
                data = resp.json()

                # API-Football wraps responses in {get:, parameters:, errors:, results:}
                if data.get("errors"):
                    error_msg = data["errors"]
                    print(f"[api-football] API errors: {error_msg}")
                    # Some errors are non-fatal (e.g. empty results for a query)
                    if isinstance(error_msg, list) and len(error_msg) > 0:
                        if isinstance(error_msg[0], str) and "rate limit" in error_msg[0].lower():
                            wait = 60
                            print(f"[api-football] rate limited, waiting {wait}s...")
                            time.sleep(wait)
                            continue

                print(
                    f"[api-football] GET {path} → {resp.status_code} "
                    f"(remaining: {remaining if remaining else '?'})"
                )
                return data
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                last_error = e
                print(f"[api-football] GET {path} error (attempt {attempt}): {e}")
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[api-football] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"ApiFootballClient: {self._max_retries} attempts failed for {path}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_response(data: dict[str, Any]) -> list[dict[str, Any]]:
        """API-Football wraps results in a 'response' key. Extract it."""
        return data.get("response", [])

    # ------------------------------------------------------------------
    # Public API — Teams
    # ------------------------------------------------------------------

    def get_teams(
        self,
        league: int | None = None,
        season: int | None = None,
        country: str | None = None,
        team_id: int | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search/list teams.

        Args:
            league: League ID (API-Football internal ID).
            season: Season year (e.g. 2024).
            country: Country name.
            team_id: Specific team ID.
            search: Team name search (>=3 chars).
        """
        params: dict[str, Any] = {}
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        if country:
            params["country"] = country
        if team_id is not None:
            params["id"] = team_id
        if search:
            params["search"] = search
        return self._extract_response(self._request("teams", params=params))

    def get_team_statistics(self, team_id: int, league: int, season: int) -> dict[str, Any]:
        """Get team statistics for a season.

        Returns form, goals, cards, fixtures breakdown, etc.
        """
        return self._request(
            "teams/statistics",
            params={
                "team": team_id,
                "league": league,
                "season": season,
            },
        )

    # ------------------------------------------------------------------
    # Public API — Players
    # ------------------------------------------------------------------

    def get_players(
        self,
        team: int | None = None,
        league: int | None = None,
        season: int | None = None,
        player_id: int | None = None,
        search: str | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """Search/list players with season statistics.

        Args:
            team: Team ID.
            league: League ID.
            season: Season year.
            player_id: Specific player ID.
            search: Player name search (>=3 chars).
        """
        params: dict[str, Any] = {"page": page}
        if team is not None:
            params["team"] = team
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        if player_id is not None:
            params["id"] = player_id
        if search:
            params["search"] = search
        return self._extract_response(self._request("players", params=params))

    # ------------------------------------------------------------------
    # Public API — Fixtures (matches)
    # ------------------------------------------------------------------

    def get_fixtures(
        self,
        fixture_id: int | None = None,
        league: int | None = None,
        season: int | None = None,
        team: int | None = None,
        date: str | None = None,  # YYYY-MM-DD
        status: str | None = None,  # NS, 1H, HT, 2H, FT, etc. or multiple comma-separated
        from_date: str | None = None,
        to_date: str | None = None,
        timezone: str = "Asia/Shanghai",
    ) -> list[dict[str, Any]]:
        """Get fixtures/matches with events, lineups, stats, players.

        Returns rich data: goals, cards, substitutions, lineups, player stats,
        match statistics (shots, possession, etc.).
        """
        params: dict[str, Any] = {"timezone": timezone}
        if fixture_id is not None:
            params["id"] = fixture_id
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        if team is not None:
            params["team"] = team
        if date:
            params["date"] = date
        if status:
            params["status"] = status
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        return self._extract_response(self._request("fixtures", params=params))

    # ------------------------------------------------------------------
    # Public API — Injuries
    # ------------------------------------------------------------------

    def get_injuries(
        self,
        league: int | None = None,
        season: int | None = None,
        team: int | None = None,
        fixture: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get injury/suspension data.

        Returns player, team, injury type, reason, expected return date.
        Limited on free tier — may return empty or restricted data.
        """
        params: dict[str, Any] = {}
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        if team is not None:
            params["team"] = team
        if fixture is not None:
            params["fixture"] = fixture
        return self._extract_response(self._request("injuries", params=params))

    # ------------------------------------------------------------------
    # Public API — Odds
    # ------------------------------------------------------------------

    def get_odds(
        self,
        fixture: int | None = None,
        league: int | None = None,
        season: int | None = None,
        date: str | None = None,
        bookmaker: int | None = None,
        bet: int | None = None,  # Bet type ID (1=Match Winner, etc.)
    ) -> list[dict[str, Any]]:
        """Get pre-match and live odds.

        Limited on free tier.
        """
        params: dict[str, Any] = {}
        if fixture is not None:
            params["fixture"] = fixture
        if league is not None:
            params["league"] = league
        if season is not None:
            params["season"] = season
        if date:
            params["date"] = date
        if bookmaker is not None:
            params["bookmaker"] = bookmaker
        if bet is not None:
            params["bet"] = bet
        return self._extract_response(self._request("odds", params=params))

    # ------------------------------------------------------------------
    # Public API — Standings
    # ------------------------------------------------------------------

    def get_standings(
        self,
        league: int,
        season: int,
        team: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get league standings."""
        params: dict[str, Any] = {
            "league": league,
            "season": season,
        }
        if team is not None:
            params["team"] = team
        return self._extract_response(self._request("standings", params=params))

    # ------------------------------------------------------------------
    # Public API — Leagues
    # ------------------------------------------------------------------

    def get_leagues(
        self,
        league_id: int | None = None,
        country: str | None = None,
        season: int | None = None,
        current: str = "true",
    ) -> list[dict[str, Any]]:
        """List available leagues/seasons."""
        params: dict[str, Any] = {"current": current}
        if league_id is not None:
            params["id"] = league_id
        if country:
            params["country"] = country
        if season is not None:
            params["season"] = season
        return self._extract_response(self._request("leagues", params=params))

    # ------------------------------------------------------------------
    # Counters
    # ------------------------------------------------------------------

    @property
    def call_count_today(self) -> int:
        return self._call_count_today

    def reset_call_count(self) -> None:
        """Reset daily counter (call at midnight)."""
        self._call_count_today = 0

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()
