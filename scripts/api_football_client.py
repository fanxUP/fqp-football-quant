"""API-Football v3 REST client.

Explicit shared quota required; x-apisports-key header.
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
from typing import Any

import httpx

from scripts.request_quota import RedisQuotaLedger
from scripts.request_transport import GovernedJsonClient, ProviderRequestError


class ApiFootballRateLimitError(RuntimeError):
    """Raised when API-SPORTS refuses a request because quota is exhausted."""


class ApiFootballClient:
    """HTTP client for v3.football.api-sports.io."""

    BASE_URL = "https://v3.football.api-sports.io/"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        min_interval: float | None = None,
        max_retries: int = 3,
        *,
        client: Any | None = None,
        ledger: RedisQuotaLedger | None = None,
    ) -> None:
        key = api_key or os.getenv("API_FOOTBALL_KEY", "")
        if not key:
            raise ValueError("API_FOOTBALL_KEY is required (env or constructor)")
        self._api_key: str = key

        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.Client(
                base_url=self.BASE_URL,
                timeout=timeout,
                follow_redirects=False,
                headers={
                    "x-apisports-key": self._api_key,
                    "Accept": "application/json",
                },
            )
        )
        self._min_interval = (
            float(os.getenv("API_FOOTBALL_MIN_INTERVAL_SECONDS", "6.1"))
            if min_interval is None
            else min_interval
        )
        self._transport = GovernedJsonClient(
            "api_football",
            self._api_key,
            client=self._client,
            ledger=ledger,
            max_attempts=max_retries,
            min_interval_seconds=self._min_interval,
        )
        self._counter_reset = 0

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            return self._transport.get(
                self.BASE_URL + path,
                params=params,
                headers={"x-apisports-key": self._api_key, "Accept": "application/json"},
            )
        except ProviderRequestError as exc:
            if exc.reason in ("rate_limited", "daily_exhausted"):
                raise ApiFootballRateLimitError("API-Football rate limit reached") from None
            raise

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

    def get_fixture_events(self, fixture_id: int) -> list[dict[str, Any]]:
        """Get goals, cards and VAR events for one fixture."""
        return self._extract_response(
            self._request("fixtures/events", params={"fixture": fixture_id})
        )

    def get_fixture_statistics(self, fixture_id: int) -> list[dict[str, Any]]:
        """Get team-level post-match statistics for one fixture."""
        return self._extract_response(
            self._request("fixtures/statistics", params={"fixture": fixture_id})
        )

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
        return self._transport.total_sends - self._counter_reset

    @property
    def last_response_meta(self) -> dict[str, Any]:
        """返回最近一次 API 响应的可审计元数据，不包含密钥。"""
        return {"errors": {}, **self._transport.last_request_meta}

    def reset_call_count(self) -> None:
        """Reset the legacy per-instance diagnostic only; never shared quota."""
        self._counter_reset = self._transport.total_sends

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._transport.close()
        if self._owns_client:
            self._client.close()
