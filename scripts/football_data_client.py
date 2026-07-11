"""football-data.org REST API client.

Free tier: 10 calls/minute, X-Auth-Token header.
Covers major European leagues, Champions League, etc.

Key endpoints (v4):
  /competions      → list leagues
  /competitions/{id}/teams → teams in league
  /teams/{id}      → team details + squad
  /matches          → match list with filters (date, competition, team)
  /persons/{id}     → player details
"""

from __future__ import annotations

import os
import time
from typing import Any

import httpx


class FootballDataClient:
    """HTTP client for api.football-data.org v4."""

    BASE_URL = "https://api.football-data.org/v4/"

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 30.0,
        min_interval: float = 6.0,  # 10 calls/min → 6s between calls
        max_retries: int = 3,
    ) -> None:
        self._api_key = api_key or os.getenv("FOOTBALL_DATA_API_KEY", "")
        if not self._api_key:
            raise ValueError("FOOTBALL_DATA_API_KEY is required (env or constructor)")

        self._client = httpx.Client(
            base_url=self.BASE_URL,
            timeout=timeout,
            headers={
                "X-Auth-Token": self._api_key,
                "Accept": "application/json",
            },
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _request(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self._rate_limit()
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                print(f"[football-data] GET {path} params={params} (attempt {attempt})")
                resp = self._client.get(path, params=params)
                self._last_request_time = time.monotonic()

                # 429 Too Many Requests → wait and retry
                if resp.status_code == 429:
                    wait = int(resp.headers.get("X-RequestCounter-Reset", "60"))
                    print(f"[football-data] rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()
                print(f"[football-data] GET {path} → {resp.status_code}")
                return data
            except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
                last_error = e
                print(f"[football-data] GET {path} error (attempt {attempt}): {e}")
                if attempt < self._max_retries:
                    backoff = 2**attempt
                    print(f"[football-data] retrying in {backoff}s...")
                    time.sleep(backoff)
        raise RuntimeError(
            f"FootballDataClient: {self._max_retries} attempts failed for {path}: {last_error}"
        )

    # ------------------------------------------------------------------
    # Public API — Competitions
    # ------------------------------------------------------------------

    def list_competitions(self, plan: str = "TIER_ONE") -> dict[str, Any]:
        """List available competitions.

        Args:
            plan: Filter by plan tier. TIER_ONE = free tier.
        """
        return self._request("competitions", params={"plan": plan})

    def get_competition(self, competition_id: int | str) -> dict[str, Any]:
        """Get a single competition by ID."""
        return self._request(f"competitions/{competition_id}")

    def get_competition_teams(self, competition_id: int | str) -> dict[str, Any]:
        """List teams in a competition."""
        return self._request(f"competitions/{competition_id}/teams")

    def get_competition_standings(self, competition_id: int | str) -> dict[str, Any]:
        """Get standings for a competition."""
        return self._request(f"competitions/{competition_id}/standings")

    def get_competition_matches(
        self,
        competition_id: int | str,
        matchday: int | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """Get matches for a competition, optionally filtered."""
        params: dict[str, Any] = {}
        if matchday is not None:
            params["matchday"] = matchday
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        return self._request(f"competitions/{competition_id}/matches", params=params)

    # ------------------------------------------------------------------
    # Public API — Teams
    # ------------------------------------------------------------------

    def get_team(self, team_id: int | str) -> dict[str, Any]:
        """Get team details including current squad."""
        return self._request(f"teams/{team_id}")

    def get_team_matches(
        self,
        team_id: int | str,
        status: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Get matches for a team."""
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status  # SCHEDULED, FINISHED, etc.
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        return self._request(f"teams/{team_id}/matches", params=params)

    # ------------------------------------------------------------------
    # Public API — Matches
    # ------------------------------------------------------------------

    def list_matches(
        self,
        date_from: str | None = None,
        date_to: str | None = None,
        competition_ids: str | None = None,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """List matches across all competitions with filters.

        Args:
            competition_ids: Comma-separated competition IDs.
            status: SCHEDULED, LIVE, FINISHED, etc.
        """
        params: dict[str, Any] = {"limit": limit}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        if competition_ids:
            params["competitions"] = competition_ids
        if status:
            params["status"] = status
        return self._request("matches", params=params)

    def get_match(self, match_id: int | str) -> dict[str, Any]:
        """Get a single match with head-to-head data."""
        return self._request(f"matches/{match_id}")

    def get_match_head2head(self, match_id: int | str, limit: int = 10) -> dict[str, Any]:
        """Get head-to-head history for a match."""
        return self._request(f"matches/{match_id}/head2head", params={"limit": limit})

    # ------------------------------------------------------------------
    # Public API — Players
    # ------------------------------------------------------------------

    def get_person(self, person_id: int | str) -> dict[str, Any]:
        """Get player/person details."""
        return self._request(f"persons/{person_id}")

    def get_person_matches(self, person_id: int | str, limit: int = 20) -> dict[str, Any]:
        """Get matches for a player."""
        return self._request(f"persons/{person_id}/matches", params={"limit": limit})

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._client.close()
